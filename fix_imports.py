import os
import re

# Fix all files in src/components/ui
ui_dir = 'src/components/ui'

for filename in os.listdir(ui_dir):
    if filename.endswith('.tsx'):
        filepath = os.path.join(ui_dir, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Remove version numbers from import statements
        new_content = re.sub(r'from "([^"]+)@[^"]*"', r'from "\1"', content)

        if new_content != content:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print(f'Fixed {filename}')
