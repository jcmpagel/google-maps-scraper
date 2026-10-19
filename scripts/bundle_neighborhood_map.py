"""Create one portable HTML file with local scripts, styles, streets and downloads."""
import argparse
import base64
import json
import mimetypes
import re
from pathlib import Path


def bundle(directory, output):
    directory = Path(directory)
    source = (directory / 'index.html').read_text()

    def stylesheet(match):
        path = directory / match[1]
        css = path.read_text()

        def asset(url):
            name = url[1].strip('"\' ')
            if name.startswith(('data:', 'http:', 'https:', '#')):
                return url[0]
            target = path.parent / name
            mime = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
            return 'url(data:' + mime + ';base64,' + base64.b64encode(target.read_bytes()).decode() + ')'

        return '<style>\n' + re.sub(r'url\(([^)]+)\)', asset, css) + '\n</style>'

    source = re.sub(r'<link rel="stylesheet" href="([^"]+)">', stylesheet, source)

    def script(match):
        text = (directory / match[1]).read_text()
        text = re.sub(r'</script', r'<\\/script', text, flags=re.I)
        return '<script>\n' + text + '\n</script>'

    source = re.sub(r'<script src="([^"]+)"></script>', script, source)
    files = {'restaurants.csv': 'text/csv;charset=utf-8', 'restaurants.kml': 'application/vnd.google-earth.kml+xml',
             'data.json': 'application/json', 'basemap.geojson': 'application/geo+json'}
    embedded = {name: base64.b64encode((directory / name).read_bytes()).decode() for name in ['restaurants.csv', 'restaurants.kml']}
    for name in files:
        source = source.replace(f'href="{name}" download', f'href="#" download="{name}" data-embedded="{name}"')
    licenses = {str(path.relative_to(directory)): path.read_text() for path in [directory / 'BASEMAP-LICENSE.txt', directory / 'basemap.source.json', *sorted((directory / 'vendor').glob('*LICENSE.txt'))]}
    source = source.replace('</body>', '<script type="application/json" id="bundled-licenses">' + json.dumps(licenses, ensure_ascii=False).replace('<', '\\u003c') + '</script>\n<script>\n' +
        '(() => { const encoded = ' + json.dumps(embedded) + '; const types = ' + json.dumps(files) + '; const urls = new Map();\n' +
        'for (const link of document.querySelectorAll("[data-embedded]")) { const name = link.dataset.embedded; if (!urls.has(name)) {\n' +
        'const value = name === "data.json" ? JSON.stringify(window.RESTAURANT_DATA) : name === "basemap.geojson" ? JSON.stringify(window.OFFLINE_BASEMAP) : Uint8Array.from(atob(encoded[name]), c => c.charCodeAt(0));\n' +
        'urls.set(name, URL.createObjectURL(new Blob([value], {type:types[name]}))); } link.href = urls.get(name); } })();\n</script>\n</body>')
    Path(output).write_text(source)
    print(json.dumps({'standalone': str(output), 'bytes': Path(output).stat().st_size}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    parser.add_argument('output')
    arguments = parser.parse_args()
    bundle(arguments.directory, arguments.output)
