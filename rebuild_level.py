import sys
import subprocess
from pathlib import Path

def main():
    if len(sys.argv) < 2:
        print("Usage: python rebuild_level.py <level.bin>")
        sys.exit(1)

    input_path = Path(sys.argv[1]).resolve()
    if not input_path.exists():
        print(f"Error: File {input_path} does not exist.")
        sys.exit(1)

    # 1. Determine temporary JSON path (read_level.py currently creates stem_data.json)
    json_path = Path(f"{input_path.stem}_data.json")

    # 2. Run read_level.py
    print(f"--- Running read_level.py on {input_path.name} ---")
    subprocess.run([sys.executable, "read_level.py", str(input_path)], check=True)

    # 3. Determine output BIN path
    output_path = Path(input_path.name)
    
    # If the output name would collide with the input file or an existing file, add a number
    if output_path.resolve() == input_path.resolve() or output_path.exists():
        counter = 1
        while True:
            candidate = Path(f"{input_path.stem}({counter}).bin")
            # Ensure it doesn't exist AND isn't the same as the input file
            if not candidate.exists() and candidate.resolve() != input_path.resolve():
                output_path = candidate
                break
            counter += 1

    # 4. Run write_level.py
    print(f"\n--- Running write_level.py to create {output_path} ---")
    subprocess.run([sys.executable, "write_level.py", str(json_path), str(output_path)], check=True)

    print(f"\nDone! Rebuilt level is at: {output_path.resolve()}")

    # 5. Cleanup prompt
    choice = input(f"\nDo you want to clean up (delete) the temporary file {json_path.name}? (y/n): ").lower()
    if choice == 'y':
        json_path.unlink()
        print(f"Deleted {json_path.name}")
    else:
        print(f"Kept {json_path.name}")

if __name__ == "__main__":
    main()
