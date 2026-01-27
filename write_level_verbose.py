import struct
import json
import sys
from pathlib import Path
from datetime import datetime

# --- LOGGING SETUP ---
class Logger:
    def __init__(self, log_path=None):
        self.log_file = None
        if log_path:
            self.log_file = open(log_path, 'w', encoding='utf-8')
    
    def log(self, message):
        timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
        full_message = f"{timestamp} {message}"
        if self.log_file:
            self.log_file.write(full_message + '\n')
            self.log_file.flush()

    def close(self):
        if self.log_file:
            self.log_file.close()

def pack_string(s, logger, desc=""):
    pos_before = None # We'll get this from the file handle
    if s is None:
        return struct.pack('<i', 0)
    encoded = s.encode('ascii') + b'\x00'
    res = struct.pack('<i', len(encoded)) + encoded
    return res

def write_level(data, output_path, logger):
    with open(output_path, 'wb') as f:
        def log_write(pos, n, desc, val):
            logger.log(f"0x{pos:X}: Wrote {n} bytes ({desc}) -> {val}")

        def write_packed(fmt, val, desc):
            pos = f.tell()
            packed = struct.pack(fmt, val)
            f.write(packed)
            log_write(pos, len(packed), desc, val)

        def write_str(s, desc):
            pos = f.tell()
            packed = pack_string(s, logger, desc)
            f.write(packed)
            logger.log(f"0x{pos:X}: Wrote string ({desc}) -> '{s}'")

        # Header
        write_packed('<i', data.get('dummy', 0), "header dummy")
        write_packed('<i', data.get('tileTypeCount', 0), "tileTypeCount")

        # 1. Tile Types
        for i, tile in enumerate(data.get('tileTypes', [])):
            write_str(tile.get('value', ''), f"tileType[{i}]")

        # Layers
        layer_count = data.get('layerCount', 0)
        write_packed('<i', layer_count, "layerCount")

        for layer_idx, layer in enumerate(data.get('layers', [])):
            logger.log(f"--- START LAYER {layer_idx + 1} ---")
            
            # A. Walls
            walls = layer.get('walls', [])
            write_packed('<i', len(walls), f"Layer {layer_idx+1} wallCount")
            for i, wall in enumerate(walls):
                pos = f.tell()
                f.write(struct.pack('<dddd', 
                    wall.get('pos_x', 0.0), wall.get('pos_y', 0.0), 
                    wall.get('width', 0.0), wall.get('length', 0.0)
                ))
                logger.log(f"0x{pos:X}: Wrote 32 bytes (Wall[{i}] doubles)")
                
                write_str(wall.get('wall_type_name', ''), f"Wall[{i}] type")
                
                flag = wall.get('has_shapes_flag', 1)
                pos = f.tell()
                f.write(struct.pack('<B', flag))
                logger.log(f"0x{pos:X}: Wrote 1 byte (Wall[{i}] has_shapes_flag) -> {flag}")
                
                if flag == 0:
                    shapes = wall.get('shapes', [])
                    write_packed('<i', len(shapes), f"Wall[{i}] shapeCount")
                    for j, shape in enumerate(shapes):
                        write_str(shape.get('shape_type_name', ''), f"Wall[{i}] Shape[{j}] type")
                        shape_data = shape.get('data', {})
                        if shape.get('shape_type_name') == "Circle":
                            pos = f.tell()
                            f.write(struct.pack('<ddd', 
                                shape_data.get('center_x', 0.0), 
                                shape_data.get('center_y', 0.0), 
                                shape_data.get('radius', 0.0)
                            ))
                            logger.log(f"0x{pos:X}: Wrote 24 bytes (Wall[{i}] Shape[{j}] Circle data)")
                        else:
                            vertices = shape_data.get('vertices', [])
                            write_packed('<i', len(vertices), f"Wall[{i}] Shape[{j}] vCount")
                            pos = f.tell()
                            for vx, vy in vertices:
                                f.write(struct.pack('<dd', vx, vy))
                            logger.log(f"0x{pos:X}: Wrote {len(vertices)*16} bytes (Wall[{i}] Shape[{j}] vertices)")
                
                write_packed('<i', wall.get('reserved', 0), f"Wall[{i}] reserved")
                write_packed('<i', wall.get('wall_id', 0), f"Wall[{i}] wall_id")

            # B. Paths
            paths = layer.get('paths', [])
            write_packed('<i', len(paths), f"Layer {layer_idx+1} pathCount")
            for i, path in enumerate(paths):
                write_str(path.get('path_name', ''), f"Path[{i}] name")
                pos = f.tell()
                p = path.get('position', [0.0, 0.0])
                f.write(struct.pack('<ddddB', p[0], p[1], path.get('extent_x_guess', 0.0), path.get('extent_y_guess', 0.0), path.get('path_flag', 0)))
                logger.log(f"0x{pos:X}: Wrote 33 bytes (Path[{i}] doubles + flag)")
                
                if path.get('path_flag', 0) == 1:
                    points = path.get('spline_points', [])
                    write_packed('<i', len(points), f"Path[{i}] pointCount")
                    pos = f.tell()
                    for pt in points:
                        p0, p1, p2 = pt.get('p0', [0,0]), pt.get('p1', [0,0]), pt.get('p2', [0,0])
                        f.write(struct.pack('<dddddd', p0[0], p0[1], p1[0], p1[1], p2[0], p2[1]))
                    logger.log(f"0x{pos:X}: Wrote {len(points)*48} bytes (Path[{i}] spline points)")
                
                write_packed('<i', path.get('internal_id_guess', 0), f"Path[{i}] internal_id")

            # C. Entities
            entities = layer.get('entities', [])
            write_packed('<i', len(entities), f"Layer {layer_idx+1} entCount")
            last_x, last_y, last_prio = 0, 0, 0
            
            for i, ent in enumerate(entities):
                write_str(ent.get('type', ''), f"Entity[{i}] type")
                
                pos = ent.get('position', [0.0, 0.0])
                curr_x_raw = int(round(pos[0] * 100))
                curr_y_raw = int(round(pos[1] * 100))
                dx, dy = curr_x_raw - last_x, curr_y_raw - last_y
                p = f.tell()
                f.write(struct.pack('<ii', dx, dy))
                logger.log(f"0x{p:X}: Wrote 8 bytes (Entity[{i}] deltaPos) -> ({dx}, {dy})")
                last_x, last_y = curr_x_raw, curr_y_raw
                
                p = f.tell()
                f.write(struct.pack('<ii', ent.get('field_158', 0), ent.get('field_15c', 0)))
                logger.log(f"0x{p:X}: Wrote 8 bytes (Entity[{i}] fields)")
                
                vec = ent.get('vec', {}).get('raw', [0, 0])
                p = f.tell()
                f.write(struct.pack('<ii', vec[0], vec[1]))
                logger.log(f"0x{p:X}: Wrote 8 bytes (Entity[{i}] vec)")
                
                p = f.tell()
                f.write(struct.pack('<ii', ent.get('field_250', {}).get('raw', 0), ent.get('rotation', {}).get('raw', 0)))
                logger.log(f"0x{p:X}: Wrote 8 bytes (Entity[{i}] rot/field)")
                
                hb = ent.get('has_box', 0)
                p = f.tell()
                f.write(struct.pack('<B', hb))
                logger.log(f"0x{p:X}: Wrote 1 byte (Entity[{i}] has_box) -> {hb}")
                if hb != 0:
                    box = ent.get('box', {})
                    p = f.tell()
                    f.write(struct.pack('<i', box.get('enabled', 0)))
                    f.write(struct.pack('<iiii', *box.get('bounds', [0,0,0,0])))
                    logger.log(f"0x{p:X}: Wrote 20 bytes (Entity[{i}] box data)")
                
                p = f.tell()
                f.write(struct.pack('BBBB', *ent.get('color', {}).get('rgba', [255, 255, 255, 255])))
                logger.log(f"0x{p:X}: Wrote 4 bytes (Entity[{i}] color)")
                
                write_packed('<d', ent.get('mass', 1.0), f"Entity[{i}] mass")
                
                curr_prio = ent.get('priority', 0)
                write_packed('<i', curr_prio - last_prio, f"Entity[{i}] prio_delta")
                last_prio = curr_prio
                
                hm = ent.get('has_move_direction', 0)
                write_packed('<i', hm, f"Entity[{i}] has_move")
                if hm == 1:
                    mv = ent.get('move_direction', {})
                    p = f.tell()
                    f.write(struct.pack('<ddidddddd', 
                        mv.get('v0', 0.0), mv.get('v1', 0.0), mv.get('flag0', 0),
                        mv.get('v2', 0.0), mv.get('v3', 0.0), mv.get('v4', 0.0),
                        mv.get('v5', 0.0), mv.get('v6', 0.0), mv.get('v7', 0.0)
                    ))
                    logger.log(f"0x{p:X}: Wrote 68 bytes (Entity[{i}] move_data)")
                
                hp = ent.get('has_path_follow', 0)
                write_packed('<i', hp, f"Entity[{i}] has_path")
                if hp == 1:
                    pf = ent.get('path_follow', {})
                    p = f.tell()
                    f.write(struct.pack('<ddidd', pf.get('v0', 0.0), pf.get('v1', 0.0), pf.get('flag0', 0), pf.get('v2', 0.0), pf.get('v3', 0.0)))
                    logger.log(f"0x{p:X}: Wrote 36 bytes (Entity[{i}] path_v0-3)")
                    write_str(pf.get('path_name', ''), f"Entity[{i}] path_name")
                    p = f.tell()
                    f.write(struct.pack('<iid', pf.get('flag1', 0), pf.get('mode', 0), pf.get('v4', 0.0)))
                    logger.log(f"0x{p:X}: Wrote 16 bytes (Entity[{i}] path_tail)")

                he = ent.get('has_emitter', 0)
                write_packed('<i', he, f"Entity[{i}] has_emitter")
                if he == 1:
                    em = ent.get('emitter', {})
                    p = f.tell()
                    f.write(struct.pack('<ddddddddddd', *[em.get(f'v{i}', 0.0) for i in range(11)]))
                    logger.log(f"0x{p:X}: Wrote 88 bytes (Entity[{i}] emitter doubles)")
                    if layer_idx >= 3:
                        write_packed('<i', em.get('reserved', 0), f"Entity[{i}] emitter_reserved")
                        write_packed('<i', em.get('end_marker', 0), f"Entity[{i}] emitter_end")

            # D. Decorations
            decorations = layer.get('decorations', [])
            write_packed('<i', len(decorations), f"Layer {layer_idx+1} decoCount")
            last_x, last_y, last_prio = 0, 0, 0
            
            for i, deco in enumerate(decorations):
                dt = deco.get('type', 0)
                p = f.tell()
                f.write(struct.pack('<B', dt))
                logger.log(f"0x{p:X}: Wrote 1 byte (Deco[{i}] type) -> {dt}")
                if dt == 0x02:
                    write_str(deco.get('string', ''), f"Deco[{i}] string")
                elif dt == 0x01:
                    write_packed('<i', deco.get('cell', 0), f"Deco[{i}] cell")
                
                pos = deco.get('position', [0.0, 0.0])
                curr_x_raw = int(round(pos[0] * 100))
                curr_y_raw = int(round(pos[1] * 100))
                p = f.tell()
                f.write(struct.pack('<ii', curr_x_raw - last_x, curr_y_raw - last_y))
                logger.log(f"0x{p:X}: Wrote 8 bytes (Deco[{i}] deltaPos) -> ({curr_x_raw-last_x}, {curr_y_raw-last_y})")
                last_x, last_y = curr_x_raw, curr_y_raw
                
                write_packed('<i', deco.get('size', {}).get('raw', 0), f"Deco[{i}] size")
                ef = deco.get('extra_flag', 0)
                p = f.tell()
                f.write(struct.pack('<B', ef))
                logger.log(f"0x{p:X}: Wrote 1 byte (Deco[{i}] extra_flag) -> {ef}")
                
                if ef != 0:
                    p = f.tell()
                    f.write(struct.pack('<BB', *deco.get('extra_bools', [0, 0])))
                    f.write(struct.pack('<iiii', *deco.get('extra_ints', [0,0,0,0])))
                    f.write(struct.pack('<i', deco.get('size_override', {}).get('raw', 0)))
                    f.write(struct.pack('<h', deco.get('extra_unknown', 0)))
                    logger.log(f"0x{p:X}: Wrote 24 bytes (Deco[{i}] extra data)")
                
                p = f.tell()
                f.write(struct.pack('BBBB', *deco.get('color_rgba', [255, 255, 255, 255])))
                logger.log(f"0x{p:X}: Wrote 4 bytes (Deco[{i}] color)")
                
                p = f.tell()
                dims = deco.get('dimensions', {}).get('raw', [0, 0])
                f.write(struct.pack('<ii', dims[0], dims[1]))
                logger.log(f"0x{p:X}: Wrote 8 bytes (Deco[{i}] dims)")
                
                cp = deco.get('priority', {}).get('total', 0)
                write_packed('<i', cp - last_prio, f"Deco[{i}] prio_delta")
                last_prio = cp

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python write_level_verbose.py <level_data.json> [output.bin]")
        sys.exit(1)
        
    input_json = Path(sys.argv[1])
    level_name = input_json.name.replace("_data.json", "")
    output_bin = sys.argv[2] if len(sys.argv) > 2 else Path(f"{level_name}_rebuilt_verbose.bin")
    log_file = f"{level_name}_write_verbose.log"
    
    logger = Logger(log_file)
    logger.log(f"Starting verbose write of {input_json.name}")
    
    try:
        with open(input_json, 'r') as f:
            data = json.load(f)
        write_level(data, output_bin, logger)
        print(f"Successfully rebuilt {input_json.name} to {output_bin}")
        print(f"Verbose log written to {log_file}")
    finally:
        logger.close()
