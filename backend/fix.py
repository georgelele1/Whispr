content = open('app.py', encoding='utf-8').read()
old = 'rf{re.escape(trigger)"'
new = 'rf"\\b{re.escape(trigger)}\\b"'
if old in content:
    content = content.replace(old, new)
    open('app.py', 'w', encoding='utf-8').write(content)
    print('FIXED')
else:
    print('NOT FOUND - may already be fixed')
