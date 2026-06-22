"""
Flask web app — SVG floor-plan cleaner with live preview.
Run:  python app.py
Then open http://localhost:5000
"""
import os
import re
import tempfile
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file

from cleaner import clean_svg, CleanOptions

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 64 * 1024 * 1024  # 64 MB upload limit

DEFAULT_SOURCE = r'C:\Users\lukasz.klimowski\Documents\Cinerglass-Electrical-Panel-Locations-Model-f10-0.svg'

# Mutable state — single-user local tool, a global is fine
state = {
    'source_path': DEFAULT_SOURCE,
    'source_name': Path(DEFAULT_SOURCE).name,
}

UPLOAD_DIR = Path(tempfile.gettempdir()) / 'svg_cleaner_uploads'
UPLOAD_DIR.mkdir(exist_ok=True)

DOWNLOAD_PATH = r'C:\Users\lukasz.klimowski\Documents\Cinerglass-walls-simple.svg'


def _make_opts(data: dict) -> CleanOptions:
    return CleanOptions(
        min_movement=float(data.get('min_movement', 20)),
        remove_arrowheads=bool(data.get('remove_arrowheads', True)),
        remove_miter_paths=bool(data.get('remove_miter_paths', True)),
        stroke_width=float(data.get('stroke_width', 1.0)),
        stroke_color=str(data.get('stroke_color', '#000000')),
    )


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/source/info')
def source_info():
    path = state['source_path']
    return jsonify({
        'name': state['source_name'],
        'path': path,
        'size_kb': round(os.path.getsize(path) / 1024, 1),
    })


@app.route('/original')
def original_svg():
    return send_file(state['source_path'], mimetype='image/svg+xml')


@app.route('/upload', methods=['POST'])
def upload():
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'error': 'No file provided'}), 400
    if not f.filename.lower().endswith('.svg'):
        return jsonify({'error': 'Only SVG files are supported'}), 400

    # Save to temp dir (overwrite previous upload with same name)
    safe_name = re.sub(r'[^\w\-. ]', '_', f.filename)
    dest = UPLOAD_DIR / safe_name
    f.save(str(dest))

    state['source_path'] = str(dest)
    state['source_name'] = safe_name

    size_kb = round(dest.stat().st_size / 1024, 1)
    return jsonify({'name': safe_name, 'size_kb': size_kb})


@app.route('/clean', methods=['POST'])
def clean():
    data = request.get_json(force=True)
    result = clean_svg(state['source_path'], _make_opts(data))
    return jsonify({
        'svg': result.svg,
        'stats': {
            'original_paths': result.original_paths,
            'kept_paths': result.kept_paths,
            'removed_paths': result.original_paths - result.kept_paths,
            'original_size_kb': round(result.original_size / 1024, 1),
            'output_size_kb': round(result.output_size / 1024, 1),
            'reduction_pct': round(100 * (1 - result.output_size / result.original_size), 1),
        }
    })


@app.route('/download', methods=['POST'])
def download():
    data = request.get_json(force=True)
    result = clean_svg(state['source_path'], _make_opts(data))
    stem = Path(state['source_name']).stem
    out_name = stem + '-walls-simple.svg'
    with open(DOWNLOAD_PATH, 'w', encoding='utf-8') as fp:
        fp.write(result.svg)
    return send_file(
        DOWNLOAD_PATH,
        mimetype='image/svg+xml',
        as_attachment=True,
        download_name=out_name,
    )


if __name__ == '__main__':
    app.run(debug=True, port=5000)
