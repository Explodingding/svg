"""
Flask web app — SVG floor-plan cleaner with live preview.
Run:  python app.py
Then open http://localhost:5000
"""
import os
import json
from flask import Flask, render_template, request, jsonify, send_file, Response

from cleaner import clean_svg, CleanOptions

app = Flask(__name__)

SVG_SOURCE = r'C:\Users\lukasz.klimowski\Documents\Cinerglass-Electrical-Panel-Locations-Model-f10-0.svg'
DOWNLOAD_PATH = r'C:\Users\lukasz.klimowski\Documents\Cinerglass-walls-simple.svg'


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/original')
def original_svg():
    return send_file(SVG_SOURCE, mimetype='image/svg+xml')


@app.route('/original/info')
def original_info():
    size = os.path.getsize(SVG_SOURCE)
    # Quick count of <path elements
    with open(SVG_SOURCE, 'r', encoding='utf-8') as f:
        content = f.read()
    import re
    path_count = len(re.findall(r'<path[\s>]', content))
    return jsonify({'size': size, 'paths': path_count})


@app.route('/clean', methods=['POST'])
def clean():
    data = request.get_json(force=True)
    opts = CleanOptions(
        min_movement=float(data.get('min_movement', 20)),
        remove_arrowheads=bool(data.get('remove_arrowheads', True)),
        remove_miter_paths=bool(data.get('remove_miter_paths', True)),
        stroke_width=float(data.get('stroke_width', 1.0)),
        stroke_color=str(data.get('stroke_color', '#000000')),
    )
    result = clean_svg(SVG_SOURCE, opts)
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
    opts = CleanOptions(
        min_movement=float(data.get('min_movement', 20)),
        remove_arrowheads=bool(data.get('remove_arrowheads', True)),
        remove_miter_paths=bool(data.get('remove_miter_paths', True)),
        stroke_width=float(data.get('stroke_width', 1.0)),
        stroke_color=str(data.get('stroke_color', '#000000')),
    )
    result = clean_svg(SVG_SOURCE, opts)
    with open(DOWNLOAD_PATH, 'w', encoding='utf-8') as f:
        f.write(result.svg)
    return send_file(
        DOWNLOAD_PATH,
        mimetype='image/svg+xml',
        as_attachment=True,
        download_name='Cinerglass-walls-simple.svg',
    )


if __name__ == '__main__':
    app.run(debug=True, port=5000)
