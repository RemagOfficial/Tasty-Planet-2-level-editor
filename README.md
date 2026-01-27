# Tasty-Planet-2-level-parser
A python script to parse level.bin files from Tasty Planet Back for Seconds

## Usage

To run the script, use the following command:

```bash
python read_level.py <level_file.bin>
```

### Example

```bash
python read_level.py levels/dino5.bin
```

### Output

The script will create a JSON file called `<level_file_name>_data.json` in the root of the scripts folder (the directory where you run the script).

For example, if you run:
```bash
python read_level.py levels/dino5.bin
```

The output file will be created as `dino5_data.json` in the current directory.
