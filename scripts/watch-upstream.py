"""Check public release metadata only; never execute upstream code or contact HA."""
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

REPO = 'thngkaiyuan/omni-pca'
ISSUE = 1

def fetch(url, data=None):
    headers = {'User-Agent': 'omni-pca-upstream-monitor', 'Accept': 'application/vnd.github+json'}
    if url.startswith('https://api.github.com/'):
        headers['Authorization'] = 'Bearer ' + os.environ['GH_TOKEN']
    req = urllib.request.Request(url, headers=headers, data=json.dumps(data).encode() if data else None)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)

def candidate(release, manifest, package):
    requirements = manifest.get('requirements', [])
    pins = [re.fullmatch(r'omni[-_]pca==([A-Za-z0-9.!+_-]+)', r) for r in requirements]
    pins = [p for p in pins if p]
    if len(pins) != 1:
        return 'review', 'Dependency format changed; manual packaging review required.'
    version = pins[0].group(1)
    files = package.get('releases', {}).get(version, [])
    if any(not f.get('yanked', False) for f in files):
        return 'candidate', f'PyPI has a non-yanked distribution for omni-pca=={version}.'
    return 'waiting', f'Required omni-pca=={version} is still unavailable on PyPI.'

def main():
    base = f'https://api.github.com/repos/{REPO}/issues/{ISSUE}'
    issue = fetch(base)
    if issue['state'] != 'open':
        print('Tracking issue closed; no action.')
        return
    comments = []
    page = 1
    while True:
        batch = fetch(base + f'/comments?per_page=100&page={page}')
        comments.extend(c['body'] for c in batch if c['user']['login'] == 'github-actions[bot]')
        if len(batch) < 100:
            break
        page += 1
    def post_once(marker, body):
        if not any(marker in c for c in comments):
            fetch(base + '/comments', {'body': marker + '\n' + body})
    run = f"https://github.com/{REPO}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    try:
        release = fetch('https://api.github.com/repos/rsp2k/omni-pca/releases/latest')
        tag = release['tag_name']
        ref = urllib.parse.quote(tag, safe='')
        url = f'https://api.github.com/repos/rsp2k/omni-pca/contents/custom_components/omni_pca/manifest.json?ref={ref}'
        import base64
        manifest = json.loads(base64.b64decode(fetch(url)['content']))
        package = fetch('https://pypi.org/pypi/omni-pca/json')
        status, evidence = candidate(release, manifest, package)
        digest = hashlib.sha256(json.dumps([tag, manifest], sort_keys=True).encode()).hexdigest()[:20]
        events = [c for c in comments if '<!-- monitor-health:' in c]
        if events and '<!-- monitor-health:failure' in events[-1]:
            fetch(base + '/comments', {'body': f'<!-- monitor-health:recovered -->\nMonitor recovered. {evidence} [Check run]({run}).'})
        if status != 'waiting':
            post_once(f'<!-- upstream-{status}:{digest} -->',
                f'@thngkaiyuan **Omni-PCA upstream {status}: {tag}**\n\n{evidence}\n\n'
                f'[Upstream release]({release["html_url"]}) · [Manifest]({url}) · [PyPI](https://pypi.org/project/omni-pca/) · [Check run]({run})\n\n'
                'The temporary fork v2026.5.16.post1 worked around a missing PyPI library release. '
                'This check confirms metadata only, not dependency installation, Home Assistant compatibility or panel behavior. '
                'Do not update blindly. Read the switch-back checklist and copy-paste agent prompt in '
                f'[the issue description](https://github.com/{REPO}/issues/{ISSUE}). '
                'Back up first, preserve the omni_pca configuration entry and entity IDs, replace only the code source, '
                'restart in a suitable window and verify read-only status. No panel writes. Roll back to the fork if checks fail.')
        print(status + ': ' + evidence)
    except Exception as exc:
        # No request bodies, credentials or arbitrary server responses in notifications.
        events = [c for c in comments if '<!-- monitor-health:' in c]
        if not events or '<!-- monitor-health:failure' not in events[-1]:
            fetch(base + '/comments', {'body': f'<!-- monitor-health:failure -->\n@thngkaiyuan Upstream check failed ({type(exc).__name__}). No conclusion about the fix is possible. Inspect [the workflow run]({run}); re-run after resolving the failure. No Home Assistant changes were made.'})
        raise

if __name__ == '__main__':
    main()
