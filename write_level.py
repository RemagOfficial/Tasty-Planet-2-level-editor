import struct
import json
import sys
from pathlib import Path

def pack_string(s):
    """Packs a string as a 4-byte length followed by ascii bytes, including a null terminator."""
    if s is None:
        return struct.pack('<i', 0)
    encoded = s.encode('ascii') + b'\x00'
    return struct.pack('<i', len(encoded)) + encoded

def write_level(json_data, output_path):
    with open(output_path, 'wb') as f:
        # 1. HEADER
        f.write(struct.pack('<i', json_data.get('dummy', 0)))
        f.write(struct.pack('<i', json_data.get('tileTypeCount', 0)))

        # 2. TILE TYPES
        for tile in json_data.get('tileTypes', []):
            f.write(pack_string(tile.get('value', '')))

        # 3. LAYERS
        layer_count = json_data.get('layerCount', 0)
        f.write(struct.pack('<i', layer_count))

        for layer_idx, layer in enumerate(json_data.get('layers', [])):
            # A. WALLS
            walls = layer.get('walls', [])
            f.write(struct.pack('<i', len(walls)))
            for wall in walls:
                # pos_x, pos_y, width, length (4 doubles)
                f.write(struct.pack('<dddd', 
                    wall.get('pos_x', 0.0), 
                    wall.get('pos_y', 0.0), 
                    wall.get('width', 0.0), 
                    wall.get('length', 0.0)
                ))
                # wall_type_name
                f.write(pack_string(wall.get('wall_type_name', '')))
                
                # has_shapes_flag
                has_shapes_flag = wall.get('has_shapes_flag', 1)
                f.write(struct.pack('<B', has_shapes_flag))
                
                if has_shapes_flag == 0:
                    shapes = wall.get('shapes', [])
                    f.write(struct.pack('<i', len(shapes)))
                    for shape in shapes:
                        shape_type = shape.get('shape_type_name', '')
                        f.write(pack_string(shape_type))
                        data = shape.get('data', {})
                        if shape_type == "Circle":
                            f.write(struct.pack('<ddd', 
                                data.get('center_x', 0.0), 
                                data.get('center_y', 0.0), 
                                data.get('radius', 0.0)
                            ))
                        else: # ConPoly
                            vertices = data.get('vertices', [])
                            f.write(struct.pack('<i', len(vertices)))
                            for vx, vy in vertices:
                                f.write(struct.pack('<dd', vx, vy))
                
                # reserved and wall_id
                f.write(struct.pack('<i', wall.get('reserved', 0)))
                f.write(struct.pack('<i', wall.get('wall_id', 0)))

            # B. PATHS
            paths = layer.get('paths', [])
            f.write(struct.pack('<i', len(paths)))
            for path in paths:
                f.write(pack_string(path.get('path_name', '')))
                pos = path.get('position', [0.0, 0.0])
                f.write(struct.pack('<dd', pos[0], pos[1]))
                f.write(struct.pack('<dd', 
                    path.get('extent_x_guess', 0.0), 
                    path.get('extent_y_guess', 0.0)
                ))
                path_flag = path.get('path_flag', 0)
                f.write(struct.pack('<B', path_flag))
                
                if path_flag == 1:
                    spline_points = path.get('spline_points', [])
                    f.write(struct.pack('<i', len(spline_points)))
                    for pt in spline_points:
                        p0 = pt.get('p0', [0.0, 0.0])
                        p1 = pt.get('p1', [0.0, 0.0])
                        p2 = pt.get('p2', [0.0, 0.0])
                        f.write(struct.pack('<dddddd', p0[0], p0[1], p1[0], p1[1], p2[0], p2[1]))
                
                f.write(struct.pack('<i', path.get('internal_id_guess', 0)))

            # C. ENTITIES
            entities = layer.get('entities', [])
            f.write(struct.pack('<i', len(entities)))
            lastX, lastY = 0, 0
            lastPrio = 0
            
            for ent in entities:
                f.write(pack_string(ent.get('type', '')))
                
                # Delta position calculation
                # read_level: lastEntPosX += dx; ent['position'] = lastEntPosX * 0.01
                # so dx = (target_pos / 0.01) - last_pos_raw
                target_pos = ent.get('position', [0.0, 0.0])
                target_x_raw = int(round(target_pos[0] * 100))
                target_y_raw = int(round(target_pos[1] * 100))
                
                dx = target_x_raw - lastX
                dy = target_y_raw - lastY
                f.write(struct.pack('<ii', dx, dy))
                lastX = target_x_raw
                lastY = target_y_raw
                
                f.write(struct.pack('<ii', ent.get('field_158', 0), ent.get('field_15c', 0)))
                
                vec = ent.get('vec', {}).get('raw', [0, 0])
                f.write(struct.pack('<ii', vec[0], vec[1]))
                
                f.write(struct.pack('<ii', 
                    ent.get('field_250', {}).get('raw', 0), 
                    ent.get('rotation', {}).get('raw', 0)
                ))
                
                has_box = ent.get('has_box', 0)
                f.write(struct.pack('<B', has_box))
                if has_box != 0:
                    box = ent.get('box', {})
                    f.write(struct.pack('<i', box.get('enabled', 0)))
                    bounds = box.get('bounds', [0, 0, 0, 0])
                    f.write(struct.pack('<iiii', bounds[0], bounds[1], bounds[2], bounds[3]))
                
                color = ent.get('color', {}).get('rgba', [255, 255, 255, 255])
                f.write(struct.pack('BBBB', *color))
                
                f.write(struct.pack('<d', ent.get('mass', 1.0)))
                
                # Priority delta
                target_prio = ent.get('priority', 0)
                prio_delta = target_prio - lastPrio
                f.write(struct.pack('<i', prio_delta))
                lastPrio = target_prio
                
                # move_direction
                has_move = ent.get('has_move_direction', 0)
                f.write(struct.pack('<i', has_move))
                if has_move == 1:
                    mv = ent.get('move_direction', {})
                    f.write(struct.pack('<dd', mv.get('v0', 0.0), mv.get('v1', 0.0)))
                    f.write(struct.pack('<i', mv.get('flag0', 0)))
                    f.write(struct.pack('<dddddd', 
                        mv.get('v2', 0.0), mv.get('v3', 0.0), mv.get('v4', 0.0),
                        mv.get('v5', 0.0), mv.get('v6', 0.0), mv.get('v7', 0.0)
                    ))
                
                # path_follow
                has_path = ent.get('has_path_follow', 0)
                f.write(struct.pack('<i', has_path))
                if has_path == 1:
                    pf = ent.get('path_follow', {})
                    f.write(struct.pack('<dd', pf.get('v0', 0.0), pf.get('v1', 0.0)))
                    f.write(struct.pack('<i', pf.get('flag0', 0)))
                    f.write(struct.pack('<dd', pf.get('v2', 0.0), pf.get('v3', 0.0)))
                    f.write(pack_string(pf.get('path_name', '')))
                    f.write(struct.pack('<i', pf.get('flag1', 0)))
                    f.write(struct.pack('<i', pf.get('mode', 0)))
                    f.write(struct.pack('<d', pf.get('v4', 0.0)))

                # emitter
                has_emitter = ent.get('has_emitter', 0)
                f.write(struct.pack('<i', has_emitter))
                emitter = ent.get('emitter', {})
                if has_emitter == 1:
                    f.write(struct.pack('<ddddddddddd', 
                        emitter.get('v0', 0.0), emitter.get('v1', 0.0), emitter.get('v2', 0.0),
                        emitter.get('v3', 0.0), emitter.get('v4', 0.0), emitter.get('v5', 0.0),
                        emitter.get('v6', 0.0), emitter.get('v7', 0.0), emitter.get('v8', 0.0),
                        emitter.get('v9', 0.0), emitter.get('v10', 0.0)
                    ))
                    if layer_idx >= 3:
                        f.write(struct.pack('<ii', 
                            emitter.get('reserved', 0), 
                            emitter.get('end_marker', 0)
                        ))

            # D. DECORATIONS
            decorations = layer.get('decorations', [])
            f.write(struct.pack('<i', len(decorations)))
            lastX, lastY = 0, 0
            lastPrio = 0
            
            for deco in decorations:
                deco_type = deco.get('type', 0)
                f.write(struct.pack('<B', deco_type))
                
                if deco_type == 0x02:
                    f.write(pack_string(deco.get('string', '')))
                elif deco_type == 0x01:
                    f.write(struct.pack('<i', deco.get('cell', 0)))
                
                # Position offsets
                target_pos = deco.get('position', [0.0, 0.0])
                target_x_raw = int(round(target_pos[0] * 100))
                target_y_raw = int(round(target_pos[1] * 100))
                
                off_x = target_x_raw - lastX
                off_y = target_y_raw - lastY
                f.write(struct.pack('<ii', off_x, off_y))
                lastX = target_x_raw
                lastY = target_y_raw
                
                f.write(struct.pack('<i', deco.get('size', {}).get('raw', 0)))
                
                extra_flag = deco.get('extra_flag', 0)
                f.write(struct.pack('<B', extra_flag))
                
                if extra_flag != 0:
                    bools = deco.get('extra_bools', [0, 0])
                    f.write(struct.pack('<BB', *bools))
                    ints = deco.get('extra_ints', [0, 0, 0, 0])
                    f.write(struct.pack('<iiii', *ints))
                    f.write(struct.pack('<i', deco.get('size_override', {}).get('raw', 0)))
                    f.write(struct.pack('<h', deco.get('extra_unknown', 0)))
                
                color = deco.get('color_rgba', [255, 255, 255, 255])
                f.write(struct.pack('BBBB', *color))
                
                dims = deco.get('dimensions', {}).get('raw', [0, 0])
                f.write(struct.pack('<ii', dims[0], dims[1]))
                
                target_prio = deco.get('priority', {}).get('total', 0)
                prio_delta = target_prio - lastPrio
                f.write(struct.pack('<i', prio_delta))
                lastPrio = target_prio

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python write_level.py <level_data.json> [output.bin]")
        sys.exit(1)
        
    input_json = Path(sys.argv[1])
    if len(sys.argv) > 2:
        output_bin = Path(sys.argv[2])
    else:
        output_bin = input_json.with_suffix('.bin_rebuilt')
        
    with open(input_json, 'r') as f:
        data = json.load(f)
        
    write_level(data, output_bin)
    print(f"Rebuilt level written to: {output_bin}")
