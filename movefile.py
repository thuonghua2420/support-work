#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import shutil


def move_files(root_path, contains_text, target_folder_name):
    moved_count = 0
    error_count = 0

    if not os.path.isdir(root_path):
        print(f"[ERROR] Folder không tồn tại: {root_path}")
        return 1

    for current_root, dirs, files in os.walk(root_path):
        for filename in files:

            if contains_text.lower() not in filename.lower():
                continue

            source_file = os.path.join(current_root, filename)

            # Tạo folder đích cùng cấp với file
            target_folder = os.path.join(current_root, target_folder_name)

            try:
                os.makedirs(target_folder, exist_ok=True)

                target_file = os.path.join(target_folder, filename)

                # Tránh trùng tên
                if os.path.exists(target_file):
                    name, ext = os.path.splitext(filename)
                    counter = 1

                    while True:
                        new_name = f"{name}_{counter}{ext}"
                        target_file = os.path.join(target_folder, new_name)

                        if not os.path.exists(target_file):
                            break

                        counter += 1

                shutil.move(source_file, target_file)

                moved_count += 1
                print(f"[MOVED] {source_file}")
                print(f"        -> {target_file}")

            except Exception as ex:
                error_count += 1
                print(f"[ERROR] {source_file}")
                print(ex)

    print("\n==========================")
    print(f"Moved  : {moved_count}")
    print(f"Errors : {error_count}")

    return 0


if _name_ == "_main_":

    if len(sys.argv) != 4:
        print("Usage:")
        print("python move_files.py <path> <contains_text> <target_folder>")
        print("")
        print("Example:")
        print('python move_files.py "D:\\Data" "invoice" "Invoices"')
        sys.exit(1)

    root_path = sys.argv[1]
    contains_text = sys.argv[2]
    target_folder_name = sys.argv[3]

    sys.exit(
        move_files(
            root_path,
            contains_text,
            target_folder_name
        )
    )