"""
SVG floor-plan cleaner — callable with configurable options.
"""
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

SVG_NS = 'http://www.w3.org/2000/svg'


@dataclass
class CleanOptions:
    min_movement: float = 20.0          # filter paths whose max coord extent < this
    remove_arrowheads: bool = True       # drop <g> groups with fill-rule:nonzero paths
    remove_miter_paths: bool = True      # drop individual paths with stroke-linejoin:miter
    stroke_width: float = 1.0
    stroke_color: str = '#000000'
    flatten_groups: bool = True          # output all paths directly in one <g>


@dataclass
class CleanResult:
    svg: str
    original_paths: int
    kept_paths: int
    original_size: int
    output_size: int
    options: CleanOptions = field(default_factory=CleanOptions)


def _path_max_extent(d: str) -> float:
    """Return max(bbox_width, bbox_height) for an SVG path d string."""
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
        t = tokens[idx]
        idx += 1
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
    w = max(xs) - min(xs) if xs else 0
    h = max(ys) - min(ys) if ys else 0
    return max(w, h)


def _is_arrowhead_group(elem) -> bool:
    """True if <g> contains paths with fill-rule:nonzero (arrowhead triangles)."""
    for child in elem:
        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
        if tag == 'path':
            style = child.get('style', '')
            if 'fill-rule:nonzero' in style or 'stroke-linejoin:miter' in style:
                return True
    return False


def _collect(elem, opts: CleanOptions, counter: dict) -> list:
    """Recursively collect wall path d-strings."""
    tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag

    if tag in ('namedview', 'metadata', 'defs', 'text', 'tspan'):
        return []

    if tag == 'g' and opts.remove_arrowheads and _is_arrowhead_group(elem):
        # Count how many paths we're skipping
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

        if opts.remove_arrowheads and 'fill-rule:nonzero' in style:
            counter['skipped_arrowhead'] += 1
            return []
        if opts.remove_miter_paths and 'stroke-linejoin:miter' in style:
            counter['skipped_miter'] += 1
            return []
        if d and _path_max_extent(d) < opts.min_movement:
            counter['skipped_small'] += 1
            return []
        if d:
            results.append(d)
            counter['kept'] += 1

    for child in elem:
        results.extend(_collect(child, opts, counter))

    return results


def clean_svg(input_path: str, opts: CleanOptions | None = None) -> CleanResult:
    if opts is None:
        opts = CleanOptions()

    import os
    original_size = os.path.getsize(input_path)

    ET.register_namespace('', SVG_NS)
    tree = ET.parse(input_path)
    root = tree.getroot()

    viewbox = root.get('viewBox', '0 0 1588 1122.6667')
    width   = root.get('width', '1588')
    height  = root.get('height', '1122.6667')

    counter = {'total': 0, 'kept': 0, 'skipped_arrowhead': 0,
               'skipped_miter': 0, 'skipped_small': 0}

    paths = _collect(root, opts, counter)

    style = (
        f'fill:none;stroke:{opts.stroke_color};stroke-width:{opts.stroke_width};'
        'stroke-linecap:round;stroke-linejoin:round;'
        'stroke-miterlimit:10;stroke-dasharray:none;stroke-opacity:1'
    )
    TRANSFORM = 'matrix(0.16,0,0,-0.16,0,1122.6667)'

    lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
        f'<svg viewBox="{viewbox}" height="{height}" width="{width}"',
        '     xmlns="http://www.w3.org/2000/svg" version="1.1">',
        f'  <g transform="{TRANSFORM}" style="{style}">',
    ]
    for i, d in enumerate(paths):
        lines.append(f'    <path id="p{i}" d="{d}"/>')
    lines += ['  </g>', '</svg>']

    svg_str = '\n'.join(lines)

    return CleanResult(
        svg=svg_str,
        original_paths=counter['total'],
        kept_paths=counter['kept'],
        original_size=original_size,
        output_size=len(svg_str.encode('utf-8')),
        options=opts,
    )
