"""Run against a fresh, disposable AgroChat server with real Azure credentials."""

import base64
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
from playwright.sync_api import expect, sync_playwright

BASE = os.getenv('AGROCHAT_TEST_URL', 'http://127.0.0.1:8091')
PASSWORD = 'test-only correct horse 32'


def checked(response):
    assert response.is_success, (response.request.url.path, response.status_code, response.text[:500])
    return response.json()


def registration(first, surname='Tester'):
    return {'first_name': first, 'surname': surname, 'password': PASSWORD, 'confirm_password': PASSWORD,
            'enrollment_code': os.getenv('AGROCHAT_ENROLLMENT_CODE', '')}


def conversation(title, content, model='gpt-6.2-sol'):
    msg = str(uuid4())
    return {'title': title, 'models': [model], 'history': {'currentId': msg, 'messages': {
        msg: {'id': msg, 'role': 'user', 'content': content, 'timestamp': int(time.time()), 'childrenIds': []},
    }}}


def check_browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(BASE)
        expect(page.get_by_role('heading', name='Who’s chatting?')).to_be_visible()
        page.get_by_role('button', name='Add profile').click()
        page.get_by_label('First name').fill('Ada')
        page.get_by_label('Surname').fill('Grower')
        page.get_by_label('Password', exact=True).fill(PASSWORD)
        page.get_by_label('Confirm password').fill('different password here')
        if page.get_by_label('Enrollment code').is_visible():
            page.get_by_label('Enrollment code').fill(os.environ['AGROCHAT_ENROLLMENT_CODE'])
        page.get_by_role('button', name='Create profile').click()
        expect(page.get_by_role('alert')).to_have_text('Passwords do not match.')
        page.get_by_label('Confirm password').fill(PASSWORD)
        page.get_by_role('button', name='Create profile').click()
        expect(page.get_by_role('heading', name='Ada Grower')).to_be_visible()
        page.reload()
        page.get_by_role('button', name='Ada Grower').click()
        page.get_by_label('Password', exact=True).fill('wrong password')
        with page.expect_response('**/agrochat/api/login') as rejected:
            page.get_by_role('button', name='Sign in', exact=True).click()
        assert rejected.value.status == 400, rejected.value.text()
        expect(page.get_by_role('alert')).to_contain_text('incorrect')

        # Simulate the server losing the profile after the picker has loaded.
        login_url = '**/agrochat/api/login'
        profiles_url = '**/agrochat/api/profiles'
        page.route(login_url, lambda route: route.fulfill(status=404, json={'detail': 'Profile not found.'}))
        page.route(profiles_url, lambda route: route.fulfill(json={'profiles': [], 'limit': 6}))
        page.get_by_label('Password', exact=True).fill(PASSWORD)
        page.get_by_role('button', name='Sign in', exact=True).click()
        expect(page.get_by_role('status')).to_contain_text('profile list has been refreshed')
        expect(page.get_by_role('dialog')).not_to_be_visible()
        expect(page.get_by_role('button', name='Ada Grower')).to_have_count(0)
        page.unroute(login_url)
        page.unroute(profiles_url)
        page.reload()
        page.get_by_role('button', name='Ada Grower').click()

        page.get_by_label('Password', exact=True).fill(PASSWORD)
        with page.expect_response('**/agrochat/api/login') as accepted:
            page.get_by_role('button', name='Sign in', exact=True).click()
        assert accepted.value.ok, accepted.value.text()
        page.wait_for_url(BASE + '/')
        account = page.get_by_role('link', name='Account & memory')
        expect(account).to_be_visible(timeout=30_000)
        expect(page.get_by_text('gpt-6.2-sol', exact=True).first).to_be_visible(timeout=30_000)
        prompt = page.locator('#chat-input')
        expect(prompt).to_be_visible()
        prompt.fill('Reply with the single word AGROREADY, without any punctuation.')
        prompt.press('Enter')
        expect(page.get_by_text('AGROREADY', exact=True).first).to_be_visible(timeout=75_000)
        if os.getenv('AGROCHAT_TEST_MCP'):
            page.get_by_role('link', name='New Chat', exact=True).click()
            page.get_by_role('button', name='More', exact=True).click()
            page.get_by_role('menuitem', name=re.compile(r'^Tools')).click()
            page.get_by_role('menuitemcheckbox', name='AgroChat smoke').click(timeout=8_000)
            prompt.fill('Call the irrigation_status tool and report its exact result.')
            prompt.press('Enter')
            expect(page.get_by_text('MCP-IRRIGATION-512', exact=True).first).to_be_visible(timeout=90_000)
        token = page.evaluate('localStorage.getItem("token")')
        page.get_by_role('button', name='Open Sidebar').click()
        expect(page.get_by_text('Projects', exact=True)).to_be_visible()
        account.click()
        expect(page.get_by_role('heading', name='Your account')).to_be_visible()
        expect(page.locator('#name')).to_have_text('Ada Grower')
        # A canvas-generated PNG avoids checking in a binary fixture.
        photo = page.evaluate('''() => { const c = document.createElement('canvas'); c.width = c.height = 32;
            const g = c.getContext('2d'); g.fillStyle = 'red'; g.fillRect(0, 0, 32, 32); return c.toDataURL().split(',')[1] }''')
        with page.expect_response('**/agrochat/api/account/photo') as uploaded:
            page.get_by_label('Choose a new photo').set_input_files(
                {'name': 'avatar.png', 'mimeType': 'image/png', 'buffer': base64.b64decode(photo)})
        assert uploaded.value.ok
        with page.expect_response('**/agrochat/api/account/photo') as removed:
            page.get_by_role('button', name='Remove photo').click()
        assert removed.value.ok
        page.get_by_text('Account closure', exact=True).click()
        page.get_by_role('button', name='Review account deletion').click()
        delete = page.get_by_role('button', name='Delete my account permanently')
        expect(delete).to_be_disabled()
        page.get_by_label('Full name').fill('wrong name')
        page.get_by_label('Current password').fill(PASSWORD)
        expect(delete).to_be_disabled()
        page.get_by_role('button', name='Close').click()
        assert not errors, errors
        browser.close()
        return token


def check_api(token):
    with httpx.Client(base_url=BASE, timeout=25, headers={'Origin': BASE}) as api:
        headers = {'Authorization': f'Bearer {token}'}
        assert api.post('/api/v1/auths/signup', json={}).status_code == 404
        assert api.post('/api/v1/auths/add', json={}, headers=headers).status_code == 404
        assert api.get('/openai/config', headers=headers).status_code == 404
        assert api.post('/agrochat/api/account/delete', json={'full_name': 'Ada Grower', 'password': PASSWORD}).status_code in (401, 403)
        assert api.post('/agrochat/api/account/delete', json={'full_name': 'Someone Else', 'password': PASSWORD}, headers=headers).status_code == 422
        models = checked(api.get('/api/models', headers=headers))
        assert {m['id'] for m in models['data']} == {'gpt-6.2-sol', 'gpt-6.2-astra'}
        with ThreadPoolExecutor() as pool:
            results = list(pool.map(lambda name: api.post('/agrochat/api/profiles', json=registration(name)),
                                    ('Bea', 'Cleo', 'Dora', 'Emi', 'Fay', 'Gia', 'Hope')))
        assert sorted(r.status_code for r in results) == [201] * 5 + [409] * 2
        assert len(checked(api.get('/agrochat/api/profiles'))['profiles']) == 6
        raised = checked(next(r for r in results if r.is_success))
        other_token = checked(api.post('/agrochat/api/login', json={'profile_id': raised['id'], 'password': PASSWORD}))['token']
        api.cookies.clear()
        other = {'Authorization': f'Bearer {other_token}'}

        project_a = checked(api.post('/api/v1/folders/', json={'name': 'Orchard A'}, headers=headers))['id']
        project_b = checked(api.post('/api/v1/folders/', json={'name': 'Orchard B'}, headers=headers))['id']
        assert api.get(f'/api/v1/folders/{project_a}', headers=other).status_code in (403, 404)
        saved = {}
        for title, content, folder in (
            ('Project A canary', 'Keep the project codename FROST-ORCHARD-701 in the summary. I generally prefer concise replies.', project_a),
            ('Project B canary', 'The project codename is RAIN-ORCHARD-808. Record it for later.', project_b),
            ('Standalone canary', 'I generally prefer metric units for agriculture discussions.', None),
        ):
            saved[title] = checked(api.post('/api/v1/chats/new', json={
                'chat': conversation(title, content), 'folder_id': folder}, headers=headers))['id']
        scoped_chat = saved['Project A canary']
        assert api.post(f'/api/v1/chats/{scoped_chat}/folder', json={'folder_id': project_b}, headers=headers).status_code == 409
        archived = checked(api.post(f'/api/v1/chats/{scoped_chat}/archive', headers=headers))
        assert archived['folder_id'] == project_a and archived['archived']
        assert api.delete(f'/api/v1/folders/{project_a}?delete_contents=false', headers=headers).status_code == 409
        old = int(time.time()) - 8 * 86400
        checked(api.post('/api/v1/chats/import', headers=headers, json={'chats': [
            {'chat': conversation('Expired canary', 'The private code is EXPIRED-404.'), 'created_at': old, 'updated_at': old}
        ]}))

        uploaded = checked(api.post('/api/v1/files/?process_in_background=false', headers=headers,
                                    files={'file': ('orchard.txt', b'The irrigation marker for the north row is AGRO-RAG-512.', 'text/plain')}))
        collection = 'file-' + uploaded['id']
        query = {'collection_name': collection, 'query': 'What is the irrigation marker for the north row?', 'k': 1}
        retrieved = checked(api.post('/api/v1/retrieval/query/doc', headers=headers, json=query))
        assert 'AGRO-RAG-512' in str(retrieved['documents'])
        assert api.post('/api/v1/retrieval/query/doc', headers=other, json=query).status_code in (403, 404)

        deadline = time.monotonic() + 160
        while time.monotonic() < deadline:
            memory = checked(api.get('/agrochat/api/account/memory', headers=headers))
            if len(memory['projects']) == 2 and memory['profile']:
                break
            time.sleep(3)
        projects = {p['name']: p['summary'] for p in memory['projects']}
        assert 'FROST-ORCHARD-701' in projects.get('Orchard A', '') and 'RAIN-ORCHARD-808' not in projects['Orchard A'], memory
        assert 'RAIN-ORCHARD-808' in projects.get('Orchard B', '') and 'FROST-ORCHARD-701' not in projects['Orchard B'], memory
        viewer = f'/agrochat/api/projects/{project_a}/memory'
        assert checked(api.get(viewer, headers=headers))['summary'] == projects['Orchard A']
        assert api.get(viewer, headers=other).status_code == 404
        assert all(canary not in memory['profile'] for canary in ('FROST-ORCHARD-701', 'RAIN-ORCHARD-808', 'EXPIRED-404'))
        assert 'Expired canary' not in {chat['title'] for chat in memory['chats']}
        assert not checked(api.get('/agrochat/api/account/memory', headers=other))['projects']
        question = 'What is the codename recorded in this project? Return only the codename.'
        completion = checked(api.post('/api/chat/completions', headers=headers, timeout=60, json={
            'model': 'gpt-6.2-astra', 'stream': False, 'parent_id': None, 'folder_id': project_a,
            'messages': [{'role': 'user', 'content': question}],
            'user_message': {'id': str(uuid4()), 'role': 'user', 'content': question, 'timestamp': int(time.time())},
            'message_ids': [{'model_id': 'gpt-6.2-astra', 'message_id': str(uuid4())}],
        }))
        answer = completion['choices'][0]['message']['content']
        assert 'FROST-ORCHARD-701' in answer and 'RAIN-ORCHARD-808' not in answer, answer
        checked(api.post('/agrochat/api/account/memory', headers=headers, json={'paused': True}))
        paused = checked(api.get('/agrochat/api/account/memory', headers=headers))
        assert paused['paused'] and not paused['chats']
        checked(api.post('/agrochat/api/account/memory', headers=headers, json={'paused': False, 'reset': True}))
        assert not checked(api.get('/agrochat/api/account/memory', headers=headers))['chats']
        checked(api.post('/agrochat/api/account/delete', headers=headers, json={'full_name': 'Ada Grower', 'password': PASSWORD}))
        assert api.get('/agrochat/api/account', headers=headers).status_code in (401, 403)
        assert checked(api.post('/agrochat/api/profiles', json=registration('New Seat')))['slot'] == 1


if __name__ == '__main__':
    with httpx.Client(base_url=BASE) as server:
        assert not checked(server.get('/agrochat/api/profiles'))['profiles'], 'Use a fresh, disposable server.'
    check_api(check_browser())
    print('AgroChat browser, account, chat, RAG, and memory smoke checks passed.')
