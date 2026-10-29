"""Small Gemini/OpenAI image-edit adapters; no batching or filesystem output."""
import base64
import io
import json
import os
from pathlib import Path
import urllib.request
import uuid
import re
from urllib.parse import urlsplit, urlunsplit

from PIL import Image

PROMPT = ('Remove only the repeated Beike/Lianjia platform watermark overlays, including '
          '贝壳, 链家 and Lianjia.com. Preserve the actual room, furniture, architectural '
          'details, signage, colors, lighting, perspective and composition. Do not beautify, '
          'redesign, add objects or remove physical objects. Reconstruct the covered texture '
          'naturally. Return the edited photograph at the original aspect ratio.')


DEFAULT_MODEL = 'gemini-3.1-flash-lite-image'
DEFAULT_ENDPOINT = 'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'


def config(path, model=None, require_key=True):
    result = {}
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                result[key.strip()] = value.strip().strip("\"'")
    for key in ('IMAGE_EDIT_ENDPOINT', 'IMAGE_EDIT_MODEL', 'IMAGE_EDIT_API_KEY'):
        result[key] = os.environ.get(key, result.get(key, ''))
    result['IMAGE_EDIT_ENDPOINT'] = result['IMAGE_EDIT_ENDPOINT'] or DEFAULT_ENDPOINT
    result['IMAGE_EDIT_API_KEY'] = result['IMAGE_EDIT_API_KEY'] or os.environ.get('GEMINI_API_KEY', '')
    endpoint = result['IMAGE_EDIT_ENDPOINT']
    parts = urlsplit(endpoint)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('Use an HTTPS edit endpoint without URL credentials, query or fragment.')
    provider = 'gemini' if parts.hostname == 'generativelanguage.googleapis.com' or ':generateContent' in parts.path else 'openai'
    result['provider'] = provider
    # Economy is the default for Gemini, including existing .env files.
    # Explicit 'configured' restores a user's configured model; never auto-upgrade.
    if model and model not in ('economy', 'configured'):
        selected = model
    elif provider == 'gemini' and model != 'configured':
        selected = DEFAULT_MODEL
    else:
        selected = result['IMAGE_EDIT_MODEL'] or (DEFAULT_MODEL if provider == 'gemini' else '')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', selected):
        raise ValueError('Set a valid image model via --model or IMAGE_EDIT_MODEL.')
    result['IMAGE_EDIT_MODEL'] = selected
    if provider == 'gemini':
        if '{model}' in endpoint:
            endpoint = endpoint.replace('{model}', selected)
        elif re.search(r'/models/[^/]+:generateContent$', parts.path):
            path = re.sub(r'/models/[^/]+:generateContent$', '/models/' + selected + ':generateContent', parts.path)
            endpoint = urlunsplit(parts._replace(path=path))
        else:
            raise ValueError('Gemini endpoint must end with /models/{model}:generateContent.')
    result['IMAGE_EDIT_ENDPOINT'] = endpoint
    if require_key and not result['IMAGE_EDIT_API_KEY']:
        raise ValueError('Missing IMAGE_EDIT_API_KEY; fill .env.')
    return result


def edit_gemini(source, settings):
    with Image.open(source) as im:
        buf = io.BytesIO()
        im.convert('RGB').save(buf, format='JPEG', quality=90)
    b64_img = base64.b64encode(buf.getvalue()).decode('ascii')

    endpoint = settings['IMAGE_EDIT_ENDPOINT']

    payload = {
        'contents': [
            {
                'parts': [
                    {
                        'inline_data': {
                            'mime_type': 'image/jpeg',
                            'data': b64_img,
                        }
                    },
                    {
                        'text': PROMPT,
                    },
                ]
            }
        ],
        'generationConfig': {
            'responseModalities': ['TEXT', 'IMAGE'],
        },
    }
    if settings['IMAGE_EDIT_MODEL'] == DEFAULT_MODEL:
        payload['generationConfig']['imageConfig'] = {'imageSize': '1K'}
        payload['generationConfig']['thinkingConfig'] = {'thinkingLevel': 'minimal'}
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'x-goog-api-key': settings['IMAGE_EDIT_API_KEY'],
        },
    )
    with urllib.request.urlopen(req, timeout=300) as response:
        res = json.load(response)

    candidates = res.get('candidates') or []
    if not candidates:
        raise ValueError('No candidates returned from Gemini API')
    parts = candidates[0].get('content', {}).get('parts', [])
    for part in parts:
        inline = part.get('inlineData') or part.get('inline_data')
        if inline and inline.get('data') and not part.get('thought'):
            return base64.b64decode(inline['data'])
    raise ValueError('Gemini returned no output image')


def edit_openai(source, settings):
    boundary = uuid.uuid4().hex
    body = bytearray()
    for key, value in {'model': settings['IMAGE_EDIT_MODEL'], 'prompt': PROMPT, 'n': '1'}.items():
        body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    with Image.open(source) as im:
        buf = io.BytesIO()
        im.convert('RGB').save(buf, format='PNG')
    body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="photo.png"\r\nContent-Type: image/png\r\n\r\n'.encode())
    body.extend(buf.getvalue())
    body.extend(f'\r\n--{boundary}--\r\n'.encode())
    req = urllib.request.Request(settings['IMAGE_EDIT_ENDPOINT'], data=bytes(body), headers={
        'Authorization': 'Bearer ' + settings['IMAGE_EDIT_API_KEY'],
        'Content-Type': 'multipart/form-data; boundary=' + boundary})
    with urllib.request.urlopen(req, timeout=300) as response:
        item = json.load(response)['data'][0]
    if item.get('b64_json'):
        return base64.b64decode(item['b64_json'])
    with urllib.request.urlopen(item['url'], timeout=120) as response:
        return response.read()


def edit(source, settings):
    if settings['provider'] == 'gemini':
        return edit_gemini(source, settings)
    return edit_openai(source, settings)
