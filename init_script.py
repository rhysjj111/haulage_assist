import os

folders = ['drivers', 'days', 'trucks', 'jobs', 'fuel', 'payslips', 'wages_calculator']

for folder in folders:
    file_path = os.path.join('haulage_app', folder, '__init__.py')  # Construct the file path

    try:
        with open(file_path, 'r') as f:
            file_content = f.read()

        # Replace 'api' with the folder name
        updated_content = file_content.replace("'api'", f"'{folder}'")

        with open(file_path, 'w') as f:
            f.write(updated_content)

        print(f"Updated {file_path} successfully!")

    except FileNotFoundError:
        print(f"File not found: {file_path}")


