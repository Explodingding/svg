"""
SVG floor-plan cleaner — callable with configurable options.
"""
import math
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

SVG_NS = 'http://www.w3.org/2000/svg'


@dataclass
class CleanOptions:
    # Threshold mode:
    #   'relative' — min_movement_pct % of the file's internal coordinate diagonal
    #   'absolute' — min_movement is a raw coordinate unit value
    threshold_mode: str = 'relative'
    min_movement_pct: float = 0.3       # % of diagonal (relative mode)
    min_movement: float = 20.0          # absolute coordinate units (absolute mode)

    remove_arrowheads: bool = True      # drop <g> groups with fill-rule:nonzero paths
    remove_miter_paths: bool = True     # drop individual paths with stroke-linejoin:miter

    stroke_width: float = 1.0
    stroke_color: str = '#000000'


@dataclass
class CleanResult:
    svg: str
    original_paths: int
    kept_paths: int
    original_size: int
    output_size: int
    coord_info: dict = field(default_factory=dict)   # viewBox, diagonal, effective threshold
    options: CleanOptions = field(default_factory=CleanOptions)


# ── Path extent ────────────────────────────────────────────────────────────────

def _path_max_extent(d: str) -> float:
    """Return max(bbox_width, bbox_height) for a path d string."""
    tokens = re.findall(r'[MmHhVvLlZzCcSsQqTtAa]|[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', d)
    xs, ys = [], []
    cx, cy = 0.0, 0.0
    cmd = None
    idx = 0

    def next_num():
        nonlocal idx
        while idx < len(tokens) and not re.match(r'^[-+]?\d', tokens[idx]):
            idx += 1
        if idx >= len(tokens):
            return None
        v = float(tokens[idx])
        idx += 1
        return v

    while idx < len(tokens):
        t = tokens[idx]; idx += 1
        if re.match(r'^[MmHhVvLlZzCcSsQqTtAa]$', t):
            cmd = t
        else:
            idx -= 1

        if cmd in ('M', 'L'):
            x = next_num(); y = next_num()
            if x is None: break
            cx, cy = x, y; xs.append(cx); ys.append(cy)
        elif cmd in ('m', 'l'):
            x = next_num(); y = next_num()
            if x is None: break
            cx += x; cy += y; xs.append(cx); ys.append(cy)
        elif cmd == 'H':
            x = next_num()
            if x is None: break
            cx = x; xs.append(cx)
        elif cmd == 'h':
            x = next_num()
            if x is None: break
            cx += x; xs.append(cx)
        elif cmd == 'V':
            y = next_num()
            if y is None: break
            cy = y; ys.append(cy)
        elif cmd == 'v':
            y = next_num()
            if y is None: break
            cy += y; ys.append(cy)
        elif cmd in ('Z', 'z'):
            pass
        elif cmd in ('C', 'c', 'S', 's', 'Q', 'q', 'T', 't', 'A', 'a'):
            while idx < len(tokens) and re.match(r'^[-+]?\d', tokens[idx]):
                idx += 1

    if not xs: xs = [0]
    if not ys: ys = [0]
    return max(max(xs) - min(xs), max(ys) - min(ys))


# ── SVG metadata helpers ───────────────────────────────────────────────────────

def _parse_viewbox(root) -> tuple[float, float, float, float]:
    """Return (min_x, min_y, width, height) from the root SVG element."""
    vb = root.get('viewBox', '')
    if vb:
        parts = re.split(r'[\s,]+', vb.strip())
        if len(parts) == 4:
            return tuple(float(p) for p in parts)
    w = float(root.get('width') or 0) or 1588
    h = float(root.get('height') or 0) or 1122
    return 0.0, 0.0, w, h


def _root_group_info(root) -> tuple[str | None, float, float]:
    """Return (transform_string, scale_x, scale_y) from the first <g> child."""
    for child in root:
        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
        if tag == 'g':
            t = child.get('transform', '')
            m = re.match(r'matrix\(\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)\s*,'
                         r'\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)', t)
            if m:
                sx = abs(float(m.group(1)))
                sy = abs(float(m.group(4)))
                return t, sx, sy
            return t or None, 1.0, 1.0
    return None, 1.0, 1.0


def _internal_diagonal(root) -> float:
    """
    Estimate the coordinate-space diagonal used by path data.
    If there's a root matrix transform (e.g. scale 0.16), the path data lives
    in a larger internal space — we un-scale the viewBox to get it.
    """
    _, _, vb_w, vb_h = _parse_viewbox(root)
    _, sx, sy = _root_group_info(root)
    # sx/sy < 1 means internal coords are larger than viewBox
    internal_w = vb_w / sx if sx > 0 else vb_w
    internal_h = vb_h / sy if sy > 0 else vb_h
    return math.sqrt(internal_w ** 2 + internal_h ** 2)


# ── Filter helpers ─────────────────────────────────────────────────────────────

def _is_arrowhead_group(elem) -> bool:
    # Only small groups (≤3 paths) can be arrowheads; whole layers are never arrowheads
    path_count = sum(
        1 for c in elem
        if (c.tag.split('}')[-1] if '}' in c.tag else c.tag) == 'path'
    )
    if path_count == 0 or path_count > 3:
        return False
    for child in elem:
        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
        if tag == 'path':
            style = child.get('style', '')
            if 'fill-rule:nonzero' in style or 'stroke-linejoin:miter' in style:
                return True
    return False


def _collect(elem, opts: CleanOptions, threshold: float, counter: dict) -> list:
    tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag

    if tag in ('namedview', 'metadata', 'defs', 'text', 'tspan'):
        return []

    if tag == 'g' and opts.remove_arrowheads and _is_arrowhead_group(elem):
        for child in elem:
            ctag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
            if ctag == 'path':
                counter['skipped_arrowhead'] += 1
        return []

    results = []

    if tag == 'path':
        counter['total'] += 1
        style = elem.get('style', '')
        d = elem.get('d', '')

        # Paths with no stroke contribute nothing to the line-art output (we override
        # fill to none anyway), so skip them regardless of their fill-rule.
        # This catches text glyphs, arrowhead fill shapes, and other decorative fills.
        if 'stroke:none' in style or elem.get('aria-label') is not None:
            counter['skipped_arrowhead'] += 1
            return []
        if opts.remove_arrowheads and 'fill-rule:nonzero' in style:
            counter['skipped_arrowhead'] += 1
            return []
        if opts.remove_miter_paths and 'stroke-linejoin:miter' in style:
            counter['skipped_miter'] += 1
            return []
        if d and _path_max_extent(d) < threshold:
            counter['skipped_small'] += 1
            return []
        if d:
            results.append((d, elem.get('transform')))
            counter['kept'] += 1

    for child in elem:
        results.extend(_collect(child, opts, threshold, counter))

    return results


# ── Public API ─────────────────────────────────────────────────────────────────

def clean_svg(input_path: str, opts: CleanOptions | None = None) -> CleanResult:
    if opts is None:
        opts = CleanOptions()

    original_size = os.path.getsize(input_path)

    ET.register_namespace('', SVG_NS)
    tree = ET.parse(input_path)
    root = tree.getroot()

    viewbox_raw = root.get('viewBox', '')
    _, _, vb_w, vb_h = _parse_viewbox(root)
    width  = root.get('width',  str(vb_w))
    height = root.get('height', str(vb_h))

    root_transform, sx, sy = _root_group_info(root)
    diagonal = _internal_diagonal(root)

    # Resolve effective threshold
    if opts.threshold_mode == 'relative':
        threshold = opts.min_movement_pct / 100.0 * diagonal
    else:
        threshold = opts.min_movement

    counter = {'total': 0, 'kept': 0,
               'skipped_arrowhead': 0, 'skipped_miter': 0, 'skipped_small': 0}

    paths = _collect(root, opts, threshold, counter)

    style = (
        f'fill:none;stroke:{opts.stroke_color};stroke-width:{opts.stroke_width};'
        'stroke-linecap:round;stroke-linejoin:round;'
        'stroke-miterlimit:10;stroke-dasharray:none;stroke-opacity:1'
    )

    g_open = f'  <g style="{style}"'
    if root_transform:
        g_open += f' transform="{root_transform}"'
    g_open += '>'

    lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
        f'<svg viewBox="{viewbox_raw or f"0 0 {vb_w} {vb_h}"}"'
        f' height="{height}" width="{width}"',
        '     xmlns="http://www.w3.org/2000/svg" version="1.1">',
        g_open,
    ]
    for i, (d, transform) in enumerate(paths):
        t = f' transform="{transform}"' if transform else ''
        lines.append(f'    <path id="p{i}" d="{d}"{t}/>')
    lines += ['  </g>', '</svg>']

    svg_str = '\n'.join(lines)

    coord_info = {
        'viewbox_w': round(vb_w, 2),
        'viewbox_h': round(vb_h, 2),
        'internal_w': round(vb_w / sx, 1) if sx else vb_w,
        'internal_h': round(vb_h / sy, 1) if sy else vb_h,
        'diagonal': round(diagonal, 1),
        'effective_threshold': round(threshold, 2),
        'has_transform': root_transform is not None,
        'scale_x': round(sx, 4),
        'scale_y': round(sy, 4),
    }

    return CleanResult(
        svg=svg_str,
        original_paths=counter['total'],
        kept_paths=counter['kept'],
        original_size=original_size,
        output_size=len(svg_str.encode('utf-8')),
        coord_info=coord_info,
        options=opts,
    )
