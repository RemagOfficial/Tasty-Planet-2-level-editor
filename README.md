# Tasty-Planet-2-level-editor
A level editor and parser for Tasty Planet Back for Seconds

## About

This project provides both a graphical level editor (`level_editor.py`) and command-line scripts to parse and write level.bin files for Tasty Planet Back for Seconds. With these tools, custom levels in Tasty Planet Back for Seconds are now fully possible! You can extract existing levels to JSON, modify them using the GUI editor or by hand, and write them back to binary format, or create entirely new custom levels from scratch.

## Level Editor GUI (level_editor.py)

The `level_editor.py` script provides a graphical user interface for editing Tasty Planet Back for Seconds levels. This is the easiest way to create and modify custom levels.

### Getting Started

#### Option 1: Use the Pre-built EXE (Windows)

For Windows users, we provide a standalone executable that doesn't require Python installation:

1. Go to the [Releases page](https://github.com/RemagOfficial/Tasty-Planet-2-level-editor/releases) and download `TP2_Level_Editor.exe`
2. Run the executable directly - no installation required!

**Note:** The EXE is a bundled version of `level_editor.py`, `read_level.py`, and `write_level.py`. If you prefer not to use a pre-built executable, you can use the Python scripts directly (see Option 2).

#### Option 2: Run from Python Script

If you have Python installed, you can run the level editor directly:

```bash
python level_editor.py
```

### Features

The Level Editor GUI provides:
- Visual editing of level entities, decorations, walls, and paths
- Point-and-click interface for easy level modification
- Real-time preview of level layout
- Undo/Redo support
- Load and save level files directly
- Entity scaling and positioning tools
- Layer visibility controls

### Usage Tips

1. **Setting up**: On first launch or via File → Select Assets Folder, choose the game's assets folder containing the levels
2. **Loading a Level**: Use the Level Selector dropdown at the top of the window to choose and load a level
3. **Editing**: Click and drag entities, walls, and other objects to reposition them
4. **Saving**: Use File → Save (or Ctrl+S) to write your changes back to a .bin file
5. **Testing**: Your modified level will be saved directly in the game's levels folder - just launch the game to test it!

## Command-Line Usage

### Reading Levels (read_level.py)

To parse a binary level file into JSON format, use the following command:

```bash
python read_level.py <level_file.bin>
```

#### Example

```bash
python read_level.py levels/dino5.bin
```

#### Output

The script will create a JSON file called `<level_file_name>_data.json` in the root of the scripts folder (the directory where you run the script).

For example, if you run:
```bash
python read_level.py levels/dino5.bin
```

The output file will be created as `dino5_data.json` in the current directory.

### Writing Levels (write_level.py)

To convert a JSON level file back into binary format, use the following command:

```bash
python write_level.py <level_data.json> [output.bin]
```

If you don't specify an output filename, the script will automatically create one with the `.bin_rebuilt` extension.

#### Example

```bash
python write_level.py dino5_data.json custom_level.bin
```

Or to use the default output filename:

```bash
python write_level.py dino5_data.json
```

This will create `dino5_data.bin_rebuilt` in the current directory.

#### Output

The script will write the binary level file to the specified output path (or `<input_file>.bin_rebuilt` if no output path is provided).

### Creating Custom Levels

To create a custom level for Tasty Planet Back for Seconds:

1. Extract an existing level to JSON:
   ```bash
   python read_level.py levels/dino5.bin
   ```

2. Edit the resulting `dino5_data.json` file to customize the level (modify entities, decorations, walls, paths, etc.)

3. Convert the modified JSON back to binary format with the **same filename** as the original level:
   ```bash
   python write_level.py dino5_data.json dino5.bin
   ```

4. Replace the original level file in your game's levels folder with your custom `dino5.bin` to use it in-game!

**Note:** Custom levels must match the filename of an existing vanilla level to work in-game. The custom level will replace the vanilla level when you play.

## Verbose Scripts

For debugging and advanced usage, verbose versions of both scripts are available. These scripts create detailed log files that track every byte read or written during the parsing/writing process.

### read_level_verbose.py

This is a verbose version of `read_level.py` that generates a detailed log file alongside the JSON output.

#### Usage

```bash
python read_level_verbose.py <level_file.bin>
```

#### Example

```bash
python read_level_verbose.py levels/dino5.bin
```

#### Output

In addition to creating the standard `<level_file_name>_data.json` file, this script also generates:
- `<level_file_name>_read_verbose.log` - A detailed log file containing:
  - Byte offsets (hex addresses) for every data structure
  - Raw byte values for each field read
  - Human-readable interpretations of the data
  - Timing information for the parsing process

This log file is invaluable for:
- Debugging level parsing issues
- Understanding the binary format structure
- Verifying that data is being read correctly
- Reverse engineering the level file format

### write_level_verbose.py

This is a verbose version of `write_level.py` that generates a detailed log file during the binary writing process.

#### Usage

```bash
python write_level_verbose.py <level_data.json>
```

#### Example

```bash
python write_level_verbose.py dino5_data.json
```

#### Output

This script creates:
- `<level_name>_rebuilt_verbose.bin` - The binary level file
- `<level_name>_rebuilt_verbose.log` - A detailed log file containing:
  - Byte offsets (hex addresses) where each data structure was written
  - Raw byte values written for each field
  - Human-readable descriptions of what was written
  - Timing information for the writing process

This log file is useful for:
- Debugging level writing issues
- Verifying the output binary matches expectations
- Comparing write logs with read logs to ensure round-trip accuracy
- Understanding how JSON data is converted back to binary format

### When to Use Verbose Scripts

Use the verbose scripts when:
- You encounter errors or unexpected behavior with level parsing/writing
- You're trying to understand the binary format structure in detail
- You need to verify that specific data is being read or written correctly
- You're developing new features or fixing bugs in the parser
- You want to compare the binary structure of different level files

For normal usage, the standard `read_level.py` and `write_level.py` scripts are sufficient and more performant.

## Rebuild Level Script (rebuild_level.py)

The `rebuild_level.py` script is a verification tool that ensures both reading and writing level files work correctly. It performs a complete round-trip conversion to validate data integrity.

### Purpose

This helper script is essential for testing and verification because it:
- Validates that `read_level.py` correctly extracts all data from binary level files
- Validates that `write_level.py` correctly encodes all data back to binary format
- Ensures no data is lost or corrupted during the conversion process
- Helps catch bugs in either the reading or writing implementation
- Provides confidence that custom levels will work in-game

### How It Works

The script performs these steps automatically:

1. **Read**: Converts the input binary level file to JSON using `read_level.py`
2. **Write**: Converts the JSON back to binary using `write_level.py`
3. **Output**: Creates a rebuilt binary file (with a different name to avoid overwriting)
4. **Cleanup**: Optionally deletes the intermediate JSON file

### Usage

```bash
python rebuild_level.py <level_file.bin>
```

### Example

```bash
python rebuild_level.py levels/dino5.bin
```

### Output

When you run `python rebuild_level.py levels/dino5.bin`, the script will:
- Create `dino5_data.json` in the current directory (the intermediate JSON representation)
- Create a rebuilt binary file in the current directory with an automatically chosen name:
  - `dino5.bin` (if no file with that name exists in the current directory and it won't conflict with the input)
  - `dino5(1).bin`, `dino5(2).bin`, etc. (if there's a naming conflict)
- Prompt you whether to delete the temporary JSON file

**Note:** The rebuilt file is always created in the current directory (where you run the script), not in the input file's directory.

### Verification

If the rebuilt binary file functions identically to the original in-game, you can be confident that:
- The reading implementation correctly parses all level data
- The writing implementation correctly encodes all level data
- No information is lost during the round-trip conversion

This is particularly useful when:
- Developing new features in the parser
- Fixing bugs in reading or writing logic
- Testing with different level files to ensure broad compatibility
- Verifying that custom level modifications will work correctly
