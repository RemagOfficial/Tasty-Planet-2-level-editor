import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import json
import os
import sys
import shutil
import copy
import zipfile
import tempfile
import xml.etree.ElementTree as ET
from read_level import read_level
from write_level import write_level

class LevelEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("TP2 Simple Level Editor")
        self.root.geometry("1200x800")

        self.level_data = None
        self.current_file = None
        self.bounds = None # (left, top, right, bottom)
        self.xml_tree = None
        self.xml_path = None
        self.goostarts = [] # List of (x, y) coordinates
        self.multilevel_data = {} # name -> {'prev_pos': (x, y), 'gootostart': bool}
        self.entity_types = [] # List of unique entity types discovered
        self.tile_types = [] # List of unique tile types discovered
        
        # State
        self.scale = 1.0
        self.offset_x = 0
        self.offset_y = 0
        self.ent_scale_var = tk.DoubleVar(value=100.0)
        self.item_data_map = {} # Maps canvas ID to data object
        self.item_to_obj = {} # Maps canvas ID to the actual object reference (for XML)
        self.tooltip = None
        self.right_click_moved = False
        
        # Undo/Redo State
        self.undo_stack = []
        self.redo_stack = []
        self.max_undo = 50
        
        # Drag and Edit state
        self.selection = [] # List of data object references
        self.is_dragging = False
        self.selection_rect = None
        self.selection_start = None
        self.clipboard = None # Stores list of {data, type, offset} or single item
        self.context_menu = None
        
        # Visibility State: {layer_idx: {type: bool}}
        self.visibility = {} 
        self.type_names = ["walls", "entities", "decorations", "paths"]
        self.preview_mode = tk.BooleanVar(value=False)
        
        self.assets_root = None
        self.levels_dir = None
        
        # Adjust paths for PyInstaller (EXE) compatibility
        if getattr(sys, 'frozen', False):
            # Running as a bundled EXE
            base_dir = os.path.dirname(sys.executable)
        else:
            # Running as a normal script
            base_dir = os.path.dirname(os.path.abspath(__file__))

        self.config_path = os.path.join(base_dir, "config.json")
        self.backup_dir = os.path.join(base_dir, "backups")
        
        if not os.path.exists(self.backup_dir):
            os.makedirs(self.backup_dir)

        # UI Components
        self.create_widgets()

        # Load config and potentially prompt for assets
        self.load_config()
        if not self.assets_root:
            self.root.after(100, self.select_assets_root)

    def load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    config = json.load(f)
                    
                    # Load types FIRST
                    self.entity_types = config.get("entity_types", [])
                    self.entity_types.sort()
                    self.tile_types = config.get("tile_types", [])
                    self.tile_types.sort()

                    path = config.get("assets_root")
                    if path and os.path.isdir(path):
                        # Use a flag to prevent set_assets_root from prompting during initial load
                        self._is_loading_config = True
                        self.set_assets_root(path)
                        self._is_loading_config = False
            except Exception as e:
                print(f"Failed to load config: {e}")

    def save_config(self):
        try:
            # Preserve existing data if current is empty
            data = {"assets_root": self.assets_root}
            if self.entity_types:
                data["entity_types"] = self.entity_types
            if self.tile_types:
                data["tile_types"] = self.tile_types
            
            # Try to preserve from existing file if local lists are empty
            if os.path.exists(self.config_path):
                with open(self.config_path, "r") as f:
                    old = json.load(f)
                    if "entity_types" not in data:
                        data["entity_types"] = old.get("entity_types", [])
                    if "tile_types" not in data:
                        data["tile_types"] = old.get("tile_types", [])

            with open(self.config_path, "w") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"Failed to save config: {e}")

    def select_assets_root(self):
        path = filedialog.askdirectory(title="Select Assets Root Folder (contains 'levels' folder)")
        if path:
            self.set_assets_root(path)
            self.save_config()
        elif not self.assets_root:
            messagebox.showwarning("Assets Required", "Please select an assets folder to enable easy level loading.")

    def set_assets_root(self, path):
        self.assets_root = path
        self.levels_dir = os.path.join(path, "levels")
        if not os.path.isdir(self.levels_dir):
            if os.path.basename(path).lower() == "levels":
                self.levels_dir = path
            else:
                messagebox.showerror("Error", f"Could not find 'levels' folder in {path}")
                self.levels_dir = None
                return
        
        self.scan_multilevels()
        self.refresh_level_list()

        # Check for discovery (Prompt if either entity or tile types are missing)
        if (not self.entity_types or not self.tile_types) and self.levels_dir:
            self.root.after(500, self.prompt_discover_assets)

    def prompt_discover_assets(self):
        if messagebox.askyesno("Discover Assets", "Possible entity types or tile types are missing from your configuration. Would you like to scan all levels to discover all possible assets?"):
            self.discover_assets()

    def discover_assets(self):
        if not self.levels_dir: return
        
        bin_files = [f for f in os.listdir(self.levels_dir) if f.lower().endswith(".bin")]
        if not bin_files: return

        # Progress window
        prog_win = tk.Toplevel(self.root)
        prog_win.title("Scanning Levels...")
        prog_win.geometry("400x120")
        prog_win.transient(self.root)
        prog_win.grab_set()

        tk.Label(prog_win, text="Discovering entity and tile types from all levels...").pack(pady=10)
        progress = ttk.Progressbar(prog_win, length=300, mode='determinate', maximum=len(bin_files))
        progress.pack(pady=5)
        
        status_lbl = tk.Label(prog_win, text="")
        status_lbl.pack()

        found_ent_types = set(self.entity_types)
        found_tile_types = set(self.tile_types)
        
        def process_batch(index):
            if index >= len(bin_files):
                self.entity_types = sorted(list(found_ent_types))
                self.tile_types = sorted(list(found_tile_types))
                self.save_config()
                prog_win.destroy()
                messagebox.showinfo("Discovery Complete", f"Found {len(self.entity_types)} entity types and {len(self.tile_types)} tile types.")
                return

            f = bin_files[index]
            status_lbl.config(text=f"Scanning {f}...")
            progress.step(1)
            
            try:
                data = read_level(os.path.join(self.levels_dir, f))
                # Collect Tile Types
                for tt in data.get('tileTypes', []):
                    if tt.get('value'):
                        found_tile_types.add(tt['value'])
                
                # Collect Entity Types
                for layer in data.get('layers', []):
                    for ent in layer.get('entities', []):
                        if ent.get('type'):
                            found_ent_types.add(ent['type'])
            except Exception as e:
                print(f"Error scanning {f}: {e}")

            # Schedule next batch to keep UI responsive
            self.root.after(1, lambda: process_batch(index + 1))

        self.root.after(100, lambda: process_batch(0))

    def scan_multilevels(self):
        self.multilevel_data = {}
        ml_dir = os.path.join(self.levels_dir, "multilevels")
        if not os.path.isdir(ml_dir):
            return
            
        for f in os.listdir(ml_dir):
            if not f.lower().endswith(".xml"):
                continue
                
            try:
                tree = ET.parse(os.path.join(ml_dir, f))
                root = tree.getroot()
                if root.tag != 'multilevel':
                    continue
                
                prev_pos = (0.0, 0.0)
                for level_node in root.findall("level"):
                    name = level_node.get("name")
                    if not name:
                        continue
                        
                    posx = float(level_node.get("posx", 0))
                    posy = float(level_node.get("posy", 0))
                    gootostart = level_node.get("gootostart", "false").lower() == "true"
                    
                    self.multilevel_data[name] = {
                        'prev_pos': prev_pos,
                        'gootostart': gootostart
                    }
                    # Update prev_pos for the next level in the chain
                    prev_pos = (posx, posy)
                    
            except Exception as e:
                print(f"Error scanning multilevel {f}: {e}")

    def refresh_level_list(self):
        if not self.levels_dir:
            return
        
        # Binary files usually have matching XMLs
        bins = [f[:-4] for f in os.listdir(self.levels_dir) if f.lower().endswith(".bin")]
        bins.sort()
        
        self.level_combo['values'] = bins
        if bins:
            self.status_var.set(f"Found {len(bins)} levels in {self.levels_dir}")

    def on_level_selected(self, event=None):
        name = self.level_var.get()
        if not name or not self.levels_dir:
            return
        
        bin_path = os.path.join(self.levels_dir, name + ".bin")
        xml_path = os.path.join(self.levels_dir, name + ".xml")
        
        if os.path.exists(bin_path):
            self.load_level_from_path(bin_path, xml_path)

    def load_level_from_path(self, bin_path, xml_path=None):
        # Create initial backups if they don't exist
        try:
            bin_name = os.path.basename(bin_path)
            bin_orig = os.path.join(self.backup_dir, bin_name)
            if not os.path.exists(bin_orig):
                shutil.copy2(bin_path, bin_orig)
            
            if xml_path and os.path.exists(xml_path):
                xml_name = os.path.basename(xml_path)
                xml_orig = os.path.join(self.backup_dir, xml_name)
                if not os.path.exists(xml_orig):
                    shutil.copy2(xml_path, xml_orig)
        except Exception as e:
            print(f"Backup failed: {e}")

        try:
            self.level_data = read_level(bin_path)
            self.current_file = bin_path
            self.xml_path = xml_path
            
            if xml_path and os.path.exists(xml_path):
                self.load_xml_bounds(xml_path)
            else:
                self.bounds = None

            # Reset visibility and selection for new level
            self.selection = []
            self.init_visibility()
            self.render_level()
            self.status_var.set(f"Loaded: {os.path.basename(bin_path)}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load level: {e}")

    def restore_current_level(self):
        if not self.current_file:
            messagebox.showwarning("Warning", "No level loaded.")
            return

        if self.preview_mode.get():
            messagebox.showwarning("Preview Mode", "Restoring to original is disabled in Preview Mode.")
            return

        bin_path = self.current_file
        xml_path = self.xml_path
        
        bin_name = os.path.basename(bin_path)
        bin_orig = os.path.join(self.backup_dir, bin_name)
        
        xml_orig = None
        if xml_path:
            xml_name = os.path.basename(xml_path)
            xml_orig = os.path.join(self.backup_dir, xml_name)

        if not os.path.exists(bin_orig):
            messagebox.showerror("Error", f"No backup found for '{bin_name}' in backups folder.")
            return

        confirm = messagebox.askyesno("Confirm Restore", 
            f"Restore '{bin_name}' to original state? All current edits will be lost.")
        if not confirm:
            return

        try:
            # Copy originals back
            shutil.copy2(bin_orig, bin_path)
            if xml_orig and os.path.exists(xml_orig):
                shutil.copy2(xml_orig, xml_path)
            
            # Reload
            self.load_level_from_path(bin_path, xml_path)
            messagebox.showinfo("Success", f"'{bin_name}' restored to original state.")
        except Exception as e:
            messagebox.showerror("Error", f"Restore failed: {e}")
        except Exception as e:
            messagebox.showerror("Error", f"Restore failed: {e}")

    def init_visibility(self):
        self.visibility = {}
        if not self.level_data:
            return
        
        layers = self.level_data.get('layers', [])
        for i in range(len(layers)):
            self.visibility[i] = {t: tk.BooleanVar(value=True) for t in self.type_names}
        
        self.update_layer_controls()

    def update_layer_controls(self):
        # Clear old controls
        for widget in self.layer_scroll_frame.winfo_children():
            widget.destroy()

        if not self.level_data:
            return

        # Master toggle button
        btn_all = tk.Button(self.layer_scroll_frame, text="Show All (All Layers)", 
                            command=self.enable_all_visibility)
        btn_all.pack(fill=tk.X, padx=5, pady=5)

        for i in range(len(self.level_data.get('layers', []))):
            frame = tk.LabelFrame(self.layer_scroll_frame, text=f"Layer {i}")
            frame.pack(fill=tk.X, padx=5, pady=2)
            
            # Use a grid for checkboxes to make them fit better
            for idx, t in enumerate(self.type_names):
                cb = tk.Checkbutton(frame, text=t.capitalize(), 
                                   variable=self.visibility[i][t],
                                   command=self.render_level)
                cb.grid(row=idx//2, column=idx%2, sticky="w")

    def enable_all_visibility(self):
        for layer_vis in self.visibility.values():
            for var in layer_vis.values():
                var.set(True)
        self.render_level()

    def create_widgets(self):
        # Menu Bar
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Save", command=self.save_file, accelerator="Ctrl+S")
        file_menu.add_command(label="Save to APK (beta)...", command=self.save_to_apk)
        file_menu.add_separator()
        file_menu.add_command(label="Restore to Original", command=self.restore_current_level)
        file_menu.add_separator()
        file_menu.add_command(label="Select Assets Folder", command=self.select_assets_root)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)

        edit_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Edit", menu=edit_menu)
        edit_menu.add_command(label="Undo", command=self.undo, accelerator="Ctrl+Z")
        edit_menu.add_command(label="Redo", command=self.redo, accelerator="Ctrl+Y")
        edit_menu.add_separator()
        edit_menu.add_command(label="Copy", command=self.copy_selected, accelerator="Ctrl+C")
        edit_menu.add_command(label="Paste", command=self.paste_item, accelerator="Ctrl+V")
        edit_menu.add_separator()
        edit_menu.add_command(label="Add Entity", command=self.add_entity, accelerator="Ctrl+E")
        edit_menu.add_command(label="Add Wall", command=self.add_wall, accelerator="Ctrl+W")
        edit_menu.add_command(label="Add Decoration", command=self.add_decoration, accelerator="Ctrl+D")
        edit_menu.add_command(label="Rediscover Assets", command=self.discover_assets)
        edit_menu.add_separator()
        edit_menu.add_command(label="Bulk Replace Entity Type", command=self.show_bulk_replace_entities)
        edit_menu.add_command(label="Bulk Replace Tile Type", command=self.show_bulk_replace_tiles)
        edit_menu.add_separator()
        edit_menu.add_command(label="Reset Camera/View", command=self.reset_view)

        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=view_menu)
        view_menu.add_command(label="Level Overview", command=self.show_level_overview)
        view_menu.add_command(label="Toggle All Layers", command=self.enable_all_visibility)
        view_menu.add_separator()
        view_menu.add_checkbutton(label="Preview Mode (Read-Only)", variable=self.preview_mode, command=self.update_ui_for_mode)

        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About / Manual", command=self.show_about)

        # Top Bar (Retained for quick access controls)
        top_bar = tk.Frame(self.root, height=40, bg="lightgrey")
        top_bar.pack(side=tk.TOP, fill=tk.X)

        # Level Dropdown (Always visible on bar)
        tk.Label(top_bar, text="Level Selector:", bg="lightgrey", font=("tahoma", 8, "bold")).pack(side=tk.LEFT, padx=(10, 2))
        self.level_var = tk.StringVar()
        self.level_combo = ttk.Combobox(top_bar, textvariable=self.level_var, state="readonly", width=30)
        self.level_combo.pack(side=tk.LEFT, padx=5, pady=5)
        self.level_combo.bind("<<ComboboxSelected>>", self.on_level_selected)

        # Legend
        tk.Label(top_bar, text="Legend:", bg="lightgrey", font=("tahoma", 8, "bold")).pack(side=tk.LEFT, padx=(20, 2))
        tk.Label(top_bar, text="● Walls", fg="blue", bg="lightgrey").pack(side=tk.LEFT, padx=2)
        tk.Label(top_bar, text="● Ents", fg="red", bg="lightgrey").pack(side=tk.LEFT, padx=2)
        tk.Label(top_bar, text="● Decos", fg="green", bg="lightgrey").pack(side=tk.LEFT, padx=2)
        tk.Label(top_bar, text="─ Paths", fg="purple", bg="lightgrey").pack(side=tk.LEFT, padx=2)
        tk.Label(top_bar, text="G GooStart", fg="#b8860b", bg="lightgrey").pack(side=tk.LEFT, padx=2)

        # Status Bar
        self.status_var = tk.StringVar(value="Ready. Open a .bin file to begin.")
        status_bar = tk.Label(self.root, textvariable=self.status_var, bd=1, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        # Main Canvas
        self.canvas = tk.Canvas(self.root, bg="white", highlightthickness=0, takefocus=True)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Right sidebar for layers
        sidebar = tk.Frame(self.root, width=200, bg="grey")
        sidebar.pack(side=tk.RIGHT, fill=tk.Y)
        sidebar.pack_propagate(False) # Force width
        
        tk.Label(sidebar, text="Layer Visibility", bg="grey", fg="white", font=("tahoma", 10, "bold")).pack(pady=5)
        
        # Scrollable area for layers
        canvas_side = tk.Canvas(sidebar, width=170, bg="grey", highlightthickness=0)
        scrollbar = tk.Scrollbar(sidebar, orient="vertical", command=canvas_side.yview)
        self.layer_scroll_frame = tk.Frame(canvas_side, bg="grey")
        
        self.layer_scroll_frame.bind(
            "<Configure>",
            lambda e: canvas_side.configure(scrollregion=canvas_side.bbox("all"))
        )

        canvas_side.create_window((0, 0), window=self.layer_scroll_frame, anchor="nw")
        canvas_side.configure(yscrollcommand=scrollbar.set)

        canvas_side.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Mouse bindings
        self.canvas.bind("<ButtonPress-1>", self.on_left_click_press)
        self.canvas.bind("<B1-Motion>", self.on_left_click_move)
        self.canvas.bind("<ButtonRelease-1>", self.on_left_click_release)

        self.canvas.bind("<ButtonPress-3>", self.on_right_click_press)
        self.canvas.bind("<B3-Motion>", self.on_right_click_move)
        self.canvas.bind("<ButtonRelease-3>", self.on_right_click_release)

        self.canvas.bind("<MouseWheel>", self.zoom)
        self.canvas.bind("<Motion>", self.on_mouse_move)
        self.last_x = 0
        self.last_y = 0
        self.panning = False

        # Global Hotkeys
        self.root.bind("<Control-z>", self.undo)
        self.root.bind("<Control-Z>", self.undo) # Shift-Z support just in case
        self.root.bind("<Control-y>", self.redo)
        self.root.bind("<Control-Y>", self.redo)
        self.root.bind("<Control-s>", lambda e: self.save_file())
        self.root.bind("<Control-S>", lambda e: self.save_file())
        self.root.bind("<Control-c>", lambda e: self.copy_selected())
        self.root.bind("<Control-C>", lambda e: self.copy_selected())
        self.root.bind("<Control-v>", lambda e: self.paste_item())
        self.root.bind("<Control-V>", lambda e: self.paste_item())
        self.root.bind("<Control-e>", lambda e: self.add_entity())
        self.root.bind("<Control-E>", lambda e: self.add_entity())
        self.root.bind("<Control-w>", lambda e: self.add_wall())
        self.root.bind("<Control-W>", lambda e: self.add_wall())
        self.root.bind("<Control-d>", lambda e: self.add_decoration())
        self.root.bind("<Control-D>", lambda e: self.add_decoration())
        self.canvas.bind("<Delete>", self.on_delete_key)

    def on_delete_key(self, event):
        if self.preview_mode.get():
            return

        # Find item under mouse
        items = self.canvas.find_overlapping(event.x-3, event.y-3, event.x+3, event.y+3)
        if not items:
            return
            
        # Try to delete the top-most valid item
        for item_id in reversed(items):
            if item_id in self.item_data_map:
                data = self.item_data_map[item_id]
                tags = self.canvas.gettags(item_id)
                
                name = "Item"
                if "entity" in tags: name = "Entity"
                elif "wall" in tags: name = "Wall"
                elif "decoration" in tags: name = "Decoration"
                else: continue # Don't delete things like paths or goostarts this way
                
                if messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete this {name}?"):
                    self.push_state()
                    removed = False
                    for layer in self.level_data.get('layers', []):
                        for key in ['entities', 'walls', 'decorations']:
                            list_to_check = layer.get(key, [])
                            if data in list_to_check:
                                list_to_check.remove(data)
                                removed = True
                                break
                        if removed: break
                    
                    if removed:
                        self.render_level()
                        self.status_var.set(f"{name} deleted.")
                return

    def on_mouse_move(self, event):
        # Tooltip logic
        # First, ensure we don't show tooltips while panning
        if self.panning:
            return

        # Use overlapping to check exactly what is under the cursor (with small halo)
        # find_closest always returns something, which can be confusing
        items = self.canvas.find_overlapping(event.x-3, event.y-3, event.x+3, event.y+3)
        
        found = False
        if items:
            # Check most recent (top) items first
            for item_id in reversed(items):
                if item_id in self.item_data_map:
                    data = self.item_data_map[item_id]
                    self.show_tooltip(event, data, item_id)
                    found = True
                    break
        
        if not found:
            self.hide_tooltip()

    def format_num(self, val):
        """Formats a value to a normal number string, avoiding scientific notation."""
        try:
            if isinstance(val, (float, int)):
                f_val = float(val)
            else:
                # Try parsing string as float (handles scientific strings from XML)
                f_val = float(str(val))
            
            # Use fixed-point notation and strip trailing zeros/decimal point
            return f"{f_val:f}".rstrip('0').rstrip('.')
        except (ValueError, TypeError):
            return str(val)

    def show_tooltip(self, event, data, item_id=None):
        if self.tooltip:
            self.tooltip.destroy()
        
        # Formatting data for display
        text_lines = []
        if isinstance(data, dict):
            # Check for tile type resolution if this is a decoration
            tile_map = None
            if 'cell' in data and self.level_data:
                tile_map = self.level_data.get('tileTypes', [])

            for k, v in data.items():
                if k in ['shapes', 'spline_points', 'move_direction', 'path_follow', 'emitter', 'box']:
                    text_lines.append(f"{k}: [...]")
                elif k == 'cell' and tile_map is not None:
                    # Resolve tile type name for decorations
                    type_name = "Unknown"
                    if 0 <= v < len(tile_map):
                        type_name = tile_map[v].get('value', 'Unknown')
                    text_lines.append(f"tile_type: {type_name}")
                elif isinstance(v, (list, tuple)):
                    # Format coordinate lists [x, y]
                    fmt_list = [self.format_num(x) for x in v]
                    text_lines.append(f"{k}: [{', '.join(fmt_list)}]")
                else:
                    text_lines.append(f"{k}: {self.format_num(v)}")
        
        tip_text = "\n".join(text_lines)
        
        x = event.x_root + 15
        y = event.y_root + 15
        
        self.tooltip = tk.Toplevel(self.root)
        self.tooltip.wm_overrideredirect(True)
        self.tooltip.wm_geometry(f"+{x}+{y}")
        
        label = tk.Label(self.tooltip, text=tip_text, justify=tk.LEFT,
                         background="#ffffe0", relief=tk.SOLID, borderwidth=1,
                         font=("tahoma", "8", "normal"))
        label.pack()

    def hide_tooltip(self):
        if self.tooltip:
            self.tooltip.destroy()
            self.tooltip = None

    def load_xml_bounds(self, xml_path):
        self.xml_path = xml_path
        try:
            self.xml_tree = ET.parse(xml_path)
            self.parse_xml_data()
        except Exception as e:
            print(f"Error parsing XML: {e}")
            self.bounds = None

    def parse_xml_data(self):
        self.goostarts = []
        if not self.xml_tree:
            return
            
        root = self.xml_tree.getroot()
        if root.tag == 'level':
            left = float(root.get('edgeleft', 0))
            top = float(root.get('edgetop', 0))
            right = float(root.get('edgeright', 0))
            bottom = float(root.get('edgebottom', 0))
            self.bounds = (left, top, right, bottom)

            # Find all goostart elements
            found_goostart = False
            for goostart in root.findall(".//goostart"):
                x = float(goostart.get('x', 0))
                y = float(goostart.get('y', 0))
                # Extract attributes for tooltip
                data = {"type": "GooStart", "source": "Level XML"}
                for attr, val in goostart.attrib.items():
                    data[attr] = val
                
                self.goostarts.append({'pos': (x, y), 'data': data, 'element': goostart})
                found_goostart = True

            # Fallback to multilevel data if no goostart in this file
            if not found_goostart:
                level_name = os.path.splitext(os.path.basename(self.xml_path))[0]
                if level_name in self.multilevel_data:
                    ml = self.multilevel_data[level_name]
                    # Use previous level's position as start
                    data = {
                        "type": "GooStart", 
                        "source": "Multilevel XML",
                        "note": "Inherited from previous level exit",
                        "x": str(ml['prev_pos'][0]),
                        "y": str(ml['prev_pos'][1])
                    }
                    self.goostarts.append({'pos': ml['prev_pos'], 'data': data})

    def push_state(self):
        """Saves current state to undo stack."""
        if not self.level_data:
            return
            
        state = {
            'level_data': copy.deepcopy(self.level_data),
            'xml_tree_str': ET.tostring(self.xml_tree.getroot(), encoding='utf-8') if self.xml_tree else None
        }
        self.undo_stack.append(state)
        if len(self.undo_stack) > self.max_undo:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def undo(self, event=None):
        if self.preview_mode.get():
            return
        if not self.undo_stack:
            return
        
        # Save current state to redo
        current_state = {
            'level_data': copy.deepcopy(self.level_data),
            'xml_tree_str': ET.tostring(self.xml_tree.getroot(), encoding='utf-8') if self.xml_tree else None
        }
        self.redo_stack.append(current_state)
        
        # Restore from undo
        prev_state = self.undo_stack.pop()
        self.apply_state(prev_state)
        self.status_var.set("Undo successful.")

    def redo(self, event=None):
        if self.preview_mode.get():
            return
        if not self.redo_stack:
            return
        
        # Save current state to undo
        current_state = {
            'level_data': copy.deepcopy(self.level_data),
            'xml_tree_str': ET.tostring(self.xml_tree.getroot(), encoding='utf-8') if self.xml_tree else None
        }
        self.undo_stack.append(current_state)
        
        # Restore from redo
        next_state = self.redo_stack.pop()
        self.apply_state(next_state)
        self.status_var.set("Redo successful.")

    def apply_state(self, state):
        self.level_data = state['level_data']
        if state['xml_tree_str']:
            import io
            self.xml_tree = ET.ElementTree(ET.fromstring(state['xml_tree_str']))
        else:
            self.xml_tree = None
        
        # Re-parse XML data to sync goostarts/bounds
        self.parse_xml_data()
        
        # Re-render and clear selection (old references are invalid)
        self.selection = []
        self.render_level()
        # Note: We don't reset visibility here to keep context

    def add_entity(self, canvas_x=None, canvas_y=None):
        if not self.level_data:
            messagebox.showwarning("Warning", "No level loaded.")
            return

        if self.preview_mode.get():
            messagebox.showwarning("Preview Mode", "Adding entities is disabled in Preview Mode.")
            return

        try:
            self.push_state()

            # Calculate position
            width = self.canvas.winfo_width()
            height = self.canvas.winfo_height()
            
            # Sync with render_level calculation
            scale = 5.0 * self.scale
            ent_scale_factor = self.ent_scale_var.get()
            
            center_x = width / 2 + self.offset_x
            center_y = height / 2 + self.offset_y

            if canvas_x is None or canvas_y is None:
                # Use current mouse position if not passed (for Ctrl+E)
                pointer_x = self.canvas.winfo_pointerx() - self.canvas.winfo_rootx()
                pointer_y = self.canvas.winfo_pointery() - self.canvas.winfo_rooty()
                
                # If mouse is outside canvas, use center
                if not (0 <= pointer_x <= width and 0 <= pointer_y <= height):
                    pointer_x, pointer_y = width/2, height/2
                
                canvas_x, canvas_y = pointer_x, pointer_y

            world_x = (canvas_x - center_x) / (scale * ent_scale_factor)
            world_y = (canvas_y - center_y) / (scale * ent_scale_factor)

            # Calculate average priority of existing entities
            avg_priority = 0
            all_prios = []
            for layer in self.level_data.get('layers', []):
                for ent in layer.get('entities', []):
                    if 'priority' in ent:
                        all_prios.append(ent['priority'])
            if all_prios:
                avg_priority = int(sum(all_prios) / len(all_prios))

            new_ent = {
                'type': 'CHANGEME',
                'position': [world_x, world_y],
                'field_158': 0,
                'field_15c': 0,
                'vec': {'raw': [0, 0]},
                'field_250': {'raw': 0},
                'rotation': {'raw': 0},
                'has_box': 0,
                'color': {'rgba': [255, 255, 255, 255]}, 
                'mass': 1.0, # 0.0 might cause physics issues in game
                'priority': avg_priority,
                'has_move_direction': 0,
                'has_path_follow': 0,
                'has_emitter': 0
            }

            # Auto-find the layer with the most entities
            layers = self.level_data.get('layers', [])
            target_layer_idx = 0
            max_ents = -1
            
            for idx, layer in enumerate(layers):
                ent_count = len(layer.get('entities', []))
                if ent_count > max_ents:
                    max_ents = ent_count
                    target_layer_idx = idx

            # Add to the chosen layer
            if 0 <= target_layer_idx < len(layers):
                layers[target_layer_idx].setdefault('entities', []).append(new_ent)
                # Ensure the target layer and Entities are visible
                if target_layer_idx in self.visibility:
                    self.visibility[target_layer_idx]['entities'].set(True)
                self.selection = [new_ent]
            else:
                messagebox.showerror("Error", "Level has no layers.")
                return

            self.render_level()
            
            # Find the newly created item on canvas to open its dialog
            new_item_id = None
            for item_id, data_obj in self.item_data_map.items():
                if data_obj is new_ent:
                    new_item_id = item_id
                    break
            
            if new_item_id:
                self.open_edit_dialog(new_ent, new_item_id)
            else:
                messagebox.showwarning("Warning", "Entity added to data but not visible at current zoom/view. Check center of map.")
            
            self.status_var.set("New entity added.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to add entity: {e}")
            print(f"Add entity error: {e}")

    def add_wall(self, canvas_x=None, canvas_y=None):
        if not self.level_data:
            messagebox.showwarning("Warning", "No level loaded.")
            return

        if self.preview_mode.get():
            messagebox.showwarning("Preview Mode", "Adding walls is disabled in Preview Mode.")
            return

        try:
            self.push_state()

            # Calculate position
            width = self.canvas.winfo_width()
            height = self.canvas.winfo_height()
            
            # Walls use simple scale (no ent_scale_factor)
            scale = 5.0 * self.scale
            center_x = width / 2 + self.offset_x
            center_y = height / 2 + self.offset_y

            if canvas_x is None or canvas_y is None:
                # Use current mouse position if not passed (for Ctrl+W)
                pointer_x = self.canvas.winfo_pointerx() - self.canvas.winfo_rootx()
                pointer_y = self.canvas.winfo_pointery() - self.canvas.winfo_rooty()
                
                # If mouse is outside canvas, use center
                if not (0 <= pointer_x <= width and 0 <= pointer_y <= height):
                    pointer_x, pointer_y = width/2, height/2
                
                canvas_x, canvas_y = pointer_x, pointer_y

            world_x = (canvas_x - center_x) / scale
            world_y = (canvas_y - center_y) / scale

            # Find max wall_id
            max_id = 0
            for layer in self.level_data.get('layers', []):
                for wall in layer.get('walls', []):
                    wid = wall.get('wall_id', 0)
                    if wid > max_id:
                        max_id = wid
            
            new_wall = {
                'pos_x': world_x,
                'pos_y': world_y,
                'width': 100.0,
                'length': 100.0,
                'wall_type_name': 'everything',
                'has_shapes_flag': 1, # 1 means no sub-shapes
                'reserved': 0,
                'wall_id': max_id + 1
            }

            # Auto-find the layer with the most walls
            layers = self.level_data.get('layers', [])
            target_layer_idx = 0
            max_walls = -1
            
            for idx, layer in enumerate(layers):
                w_count = len(layer.get('walls', []))
                if w_count > max_walls:
                    max_walls = w_count
                    target_layer_idx = idx

            # Add to the chosen layer
            if 0 <= target_layer_idx < len(layers):
                layers[target_layer_idx].setdefault('walls', []).append(new_wall)
                # Ensure the target layer and Walls are visible
                if target_layer_idx in self.visibility:
                    self.visibility[target_layer_idx]['walls'].set(True)
            else:
                messagebox.showerror("Error", "Level has no layers.")
                return

            self.render_level()
            
            # Find the newly created item on canvas to open its dialog
            new_item_id = None
            for item_id, data_obj in self.item_data_map.items():
                if data_obj is new_wall:
                    new_item_id = item_id
                    break
            
            if new_item_id:
                self.open_edit_dialog(new_wall, new_item_id)
            else:
                messagebox.showwarning("Warning", "Wall added to data but not visible at current zoom/view.")
            
            self.status_var.set(f"Added new wall 'everything' with ID {new_wall['wall_id']}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to add wall: {e}")

    def add_decoration(self, canvas_x=None, canvas_y=None):
        if not self.level_data:
            messagebox.showwarning("Warning", "No level loaded.")
            return

        if self.preview_mode.get():
            messagebox.showwarning("Preview Mode", "Adding decorations is disabled in Preview Mode.")
            return

        try:
            self.push_state()

            # Calculate position
            width = self.canvas.winfo_width()
            height = self.canvas.winfo_height()
            scale = 5.0 * self.scale
            center_x = width / 2 + self.offset_x
            center_y = height / 2 + self.offset_y

            if canvas_x is None or canvas_y is None:
                # Use current mouse position if not passed (for Ctrl+D)
                pointer_x = self.canvas.winfo_pointerx() - self.canvas.winfo_rootx()
                pointer_y = self.canvas.winfo_pointery() - self.canvas.winfo_rooty()
                
                # If mouse is outside canvas, use center
                if not (0 <= pointer_x <= width and 0 <= pointer_y <= height):
                    pointer_x, pointer_y = width/2, height/2
                
                canvas_x, canvas_y = pointer_x, pointer_y

            world_x = (canvas_x - center_x) / scale
            world_y = (canvas_y - center_y) / scale

            # Default to first tile type or 0
            cell_idx = 0
            
            new_deco = {
                'cell': cell_idx,
                'position': [world_x, world_y],
                'field_24': 0,
                'rgba': [255, 255, 255, 255]
            }

            # Auto-find the layer with the most decorations
            layers = self.level_data.get('layers', [])
            target_layer_idx = 0
            max_decos = -1
            
            for idx, layer in enumerate(layers):
                d_count = len(layer.get('decorations', []))
                if d_count > max_decos:
                    max_decos = d_count
                    target_layer_idx = idx

            if 0 <= target_layer_idx < len(layers):
                layers[target_layer_idx].setdefault('decorations', []).append(new_deco)
                if target_layer_idx in self.visibility:
                    self.visibility[target_layer_idx]['decorations'].set(True)
            else:
                messagebox.showerror("Error", "Level has no layers.")
                return

            self.render_level()
            
            # Find and open dialog
            new_item_id = None
            for item_id, data_obj in self.item_data_map.items():
                if data_obj is new_deco:
                    new_item_id = item_id
                    break
            
            if new_item_id:
                self.open_edit_dialog(new_deco, new_item_id)
            
            self.status_var.set("New decoration added.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to add decoration: {e}")

    def save_file(self):
        if not self.level_data:
            messagebox.showwarning("Warning", "No level data to save.")
            return

        if self.preview_mode.get():
            messagebox.showwarning("Preview Mode", "Saving is disabled in Preview Mode. Toggle Preview Mode in the View menu to enable saving.")
            return

        # Cleanup unused Tile Types and Remap Indices
        try:
            used_type_names = set()
            tile_types = self.level_data.get('tileTypes', [])
            
            # Find all types currently in use
            for layer in self.level_data.get('layers', []):
                for deco in layer.get('decorations', []):
                    cell_idx = deco.get('cell', 0)
                    if 0 <= cell_idx < len(tile_types):
                        type_name = tile_types[cell_idx].get('value')
                        if type_name:
                            used_type_names.add(type_name)
            
            # Rebuild tileTypes list with only used ones (sorted for consistency)
            new_tile_types_list = sorted(list(used_type_names))
            new_tile_types = [{'value': name} for name in new_tile_types_list]
            name_to_new_idx = {name: i for i, name in enumerate(new_tile_types_list)}
            
            # Remap decoration cell indices
            for layer in self.level_data.get('layers', []):
                for deco in layer.get('decorations', []):
                    cell_idx = deco.get('cell', 0)
                    if 0 <= cell_idx < len(tile_types):
                        type_name = tile_types[cell_idx].get('value')
                        if type_name in name_to_new_idx:
                            deco['cell'] = name_to_new_idx[type_name]
            
            self.level_data['tileTypes'] = new_tile_types
            self.level_data['tileTypeCount'] = len(new_tile_types)
        except Exception as e:
            print(f"Warning: Tile type cleanup failed: {e}")

        # Integrity Check: No CHANGEME types
        for layer in self.level_data.get('layers', []):
            for ent in layer.get('entities', []):
                if ent.get('type') == "CHANGEME":
                    messagebox.showerror("Export Blocked", "One or more entities still have the type 'CHANGEME'. Please edit or delete them before saving.")
                    return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".bin",
            filetypes=[("Binary Files", "*.bin")],
            initialfile=os.path.basename(self.current_file) if self.current_file else "level.bin"
        )
        if not file_path:
            return

        try:
            write_level(self.level_data, file_path)
            # Automatic XML saving if it exists
            if self.xml_tree and self.xml_path:
                try:
                    self.xml_tree.write(self.xml_path, encoding='utf-8', xml_declaration=True)
                    xml_msg = f" and XML to {os.path.basename(self.xml_path)}"
                except:
                    xml_msg = " (XML Save Failed)"
            else:
                xml_msg = ""
            
            messagebox.showinfo("Success", f"Saved to {os.path.basename(file_path)}{xml_msg}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save level: {e}")

    def save_to_apk(self):
        if not self.level_data:
            messagebox.showwarning("Warning", "No level data to save.")
            return

        apk_path = filedialog.askopenfilename(
            title="Select Target APK File",
            filetypes=[("APK Files", "*.apk")]
        )
        if not apk_path:
            return

        # Prepare filenames
        base_name = os.path.basename(self.current_file) if self.current_file else "level.bin"
        xml_name = os.path.basename(self.xml_path) if self.xml_path else base_name.replace(".bin", ".xml")

        try:
            # Temporary files to store the bin and xml data
            temp_dir = tempfile.mkdtemp()
            temp_bin = os.path.join(temp_dir, base_name)
            temp_xml = os.path.join(temp_dir, xml_name)
            
            # Save the level to temp files
            write_level(self.level_data, temp_bin)
            if self.xml_tree:
                self.xml_tree.write(temp_xml, encoding='utf-8', xml_declaration=True)
            
            # Create a new temporary APK
            fd, new_apk_path = tempfile.mkstemp(suffix=".apk")
            os.close(fd)
            
            target_dir = "assets/assets/levels/"
            files_to_replace = {
                target_dir + base_name: temp_bin
            }
            if self.xml_tree:
                files_to_replace[target_dir + xml_name] = temp_xml

            found_target_dir = False
            
            with zipfile.ZipFile(apk_path, 'r') as zin:
                # Check if directory exists
                for name in zin.namelist():
                    if name.startswith(target_dir):
                        found_target_dir = True
                        break
                
                if not found_target_dir:
                    shutil.rmtree(temp_dir)
                    os.remove(new_apk_path)
                    messagebox.showerror("Error", f"Target directory '{target_dir}' not found in APK. Is this the correct Tasty Planet 2 APK?")
                    return

                with zipfile.ZipFile(new_apk_path, 'w') as zout:
                    for item in zin.infolist():
                        # Skip files we are replacing AND the old signature
                        if item.filename not in files_to_replace and not item.filename.startswith("META-INF/"):
                            zout.writestr(item, zin.read(item.filename))
                    
                    # Add our new files
                    for arc_path, local_path in files_to_replace.items():
                        zout.write(local_path, arc_path)
            
            # Backup original APK before replacing
            backup_apk = apk_path + ".bak"
            if not os.path.exists(backup_apk):
                shutil.copy2(apk_path, backup_apk)

            # Replace original APK with the modified one
            shutil.move(new_apk_path, apk_path)
            
            # Clean up
            shutil.rmtree(temp_dir)
            
            # Auto-Signing Opportunity
            signed_msg = ""
            # Ask if the user wants to sign, providing context about why they might say no
            choice = messagebox.askyesnocancel("Sign APK", 
                "APK updated! Would you like to automatically sign the APK now?\n\n"
                "Yes: Sign with a debug key (Installable immediately).\n"
                "No: Save without signing (You must sign it manually later).\n"
                "Cancel: Abort the process.")
            
            if choice is True: # Yes
                success, msg = self.sign_apk(apk_path)
                if success:
                    signed_msg = "\n\nAPK has been SIGNED with a debug key and should be installable."
                else:
                    signed_msg = f"\n\nAutomatic signing failed: {msg}\nYou will need to sign it manually."
            elif choice is False: # No
                signed_msg = "\n\nAPK saved WITHOUT signing. You must sign it before installing."
            else: # Cancel
                return

            messagebox.showinfo("Success", f"APK Updated successfully!\nSaved to: {target_dir}{signed_msg}")
            self.status_var.set(f"Published level to APK: {apk_path}")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to modify APK: {e}")
            import traceback
            traceback.print_exc()

    def sign_apk(self, apk_path):
        import subprocess
        
        # Paths for keystore
        base_dir = os.path.dirname(os.path.abspath(__file__)) if not getattr(sys, 'frozen', False) else os.path.dirname(sys.executable)
        keystore_path = os.path.join(base_dir, "debug.keystore")
        alias = "debug"
        password = "androiddebug"
        
        try:
            # 1. Check if jarsigner and keytool exist
            jarsigner = shutil.which("jarsigner")
            if not jarsigner:
                # Try common locations if not in PATH (some Windows users have it but not in path)
                potential_paths = [
                    r"C:\Program Files\AdoptOpenJDK\jdk-16.0.1.9-hotspot\bin\jarsigner.exe",
                    r"C:\Program Files (x86)\Java\jdk1.8.0_291\bin\jarsigner.exe"
                ]
                for p in potential_paths:
                    if os.path.exists(p):
                        jarsigner = p
                        break
            
            keytool = shutil.which("keytool")
            if not keytool:
                potential_paths = [
                    r"C:\Program Files\AdoptOpenJDK\jdk-16.0.1.9-hotspot\bin\keytool.exe",
                    r"C:\Program Files (x86)\Java\jdk1.8.0_291\bin\keytool.exe"
                ]
                for p in potential_paths:
                    if os.path.exists(p):
                        keytool = p
                        break
            
            if not jarsigner:
                return False, (
                    "Could not find 'jarsigner.exe'.\n\n"
                    "This tool is part of the Java Development Kit (JDK) and is required to make the APK installable.\n\n"
                    "HOW TO FIX:\n"
                    "1. Install the Java JDK (Recommended: Adoptium Temurin or Oracle JDK).\n"
                    "2. Add the JDK 'bin' folder to your Windows System PATH environment variable.\n"
                    "3. Or install it to the default 'C:\\Program Files\\Java' directory."
                )

            # 2. Check if keystore exists, if not, create it
            if not os.path.exists(keystore_path):
                if not keytool:
                    return False, (
                        "Could not find 'keytool.exe'.\n\n"
                        "This tool is required to create a new signing key (debug.keystore).\n"
                        "Please ensure the Java JDK is correctly installed and its 'bin' folder is in your PATH."
                    )
                
                cmd = [
                    keytool, "-genkey", "-v", 
                    "-keystore", keystore_path, 
                    "-storepass", password, 
                    "-alias", alias, 
                    "-keypass", password, 
                    "-keyalg", "RSA", 
                    "-keysize", "2048", 
                    "-validity", "10000", 
                    "-dname", "cn=TP2Editor"
                ]
                subprocess.run(cmd, check=True, capture_output=True)

            # 3. Sign the APK
            # Note: SIGALG and DIGESTALG are important for older android compatibility
            cmd = [
                jarsigner, "-sigalg", "SHA1withRSA", 
                "-digestalg", "SHA1", 
                "-keystore", keystore_path, 
                "-storepass", password, 
                apk_path, alias
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return False, f"Jarsigner failed: {result.stderr}"
                
            return True, "Success"
            
        except Exception as e:
            return False, str(e)

    def update_ui_for_mode(self):
        if self.preview_mode.get():
            self.root.title("TP2 Simple Level Editor (PREVIEW MODE - READ ONLY)")
            self.status_var.set("Preview Mode Enabled: Editing and Saving are disabled.")
        else:
            self.root.title("TP2 Simple Level Editor")
            self.status_var.set("Preview Mode Disabled: Editing enabled.")

    def show_about(self):
        about_text = """TP2 Simple Level Editor
-----------------------------------------
A specialized tool for modding Tasty Planet 2 level files.

EDITOR FEATURES:
• Comprehensive binary (.bin) and metadata (.xml) editing.
• Multi-layer visibility and editing (8 distinct layers).
• Automatic backups and 'Restore to Original' safety system.
• Robust Undo/Redo stack (50 steps).
• Intelligent Entity Discovery (scans all game levels for types).
• Coordinate-accurate object spawning.

CONTROL SCHEME:
• Right-Click Drag: Pan the map.
• Mouse Wheel: Zoom in/out.
• Left-Click Drag: Move entities and walls.
• Right-Click (on object): Open context menu to Copy, Edit, or Delete.
• Right-Click (empty space): Paste copied item at cursor.
• Delete: Quick-delete object under mouse cursor.
• Ctrl + C / Ctrl + V: Copy and Paste object under mouse.

HOTKEYS:
• Ctrl + S: Save all changes (.bin & .xml).
• Ctrl + Z: Undo last action.
• Ctrl + Y: Redo action.
• Ctrl + C: Copy object under mouse or selected object.
• Ctrl + V: Paste copied object at mouse cursor.
• Ctrl + E: Add new Entity at screen center.
• Ctrl + W: Add new Wall at screen center.

TIPS:
• The editor automatically target the 'gameplay layer' when adding objects.
• Use the 'Level Overview' (View menu) to find hidden entities or paths."""

        dialog = tk.Toplevel(self.root)
        dialog.title("About TP2 Level Editor")
        dialog.geometry("450x550")
        
        text_widget = tk.Text(dialog, padx=15, pady=15, font=("tahoma", 9), wrap=tk.WORD, bg="#f0f0f0", relief=tk.FLAT)
        text_widget.insert(tk.END, about_text)
        text_widget.config(state=tk.DISABLED)
        text_widget.pack(fill=tk.BOTH, expand=True)
        
        tk.Button(dialog, text="Got it!", command=dialog.destroy, width=15).pack(pady=10)

    def show_level_overview(self):
        if not self.level_data:
            messagebox.showinfo("Overview", "No level loaded.")
            return

        entity_counts = {}
        path_names = []
        
        for layer in self.level_data.get('layers', []):
            for ent in layer.get('entities', []):
                etype = ent.get('type', 'Unknown')
                entity_counts[etype] = entity_counts.get(etype, 0) + 1
            for path in layer.get('paths', []):
                pname = path.get('path_name', 'Unnamed Path')
                path_names.append(pname)

        dialog = tk.Toplevel(self.root)
        dialog.title("Level Overview")
        dialog.geometry("400x600")
        
        # Entities section
        tk.Label(dialog, text="Entity Types & Counts", font=("tahoma", 10, "bold")).pack(pady=(10, 5))
        ent_frame = tk.Frame(dialog)
        ent_frame.pack(fill=tk.BOTH, expand=True, padx=10)
        
        ent_lb = tk.Listbox(ent_frame, font=("tahoma", 9))
        ent_lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb1 = tk.Scrollbar(ent_frame, command=ent_lb.yview)
        sb1.pack(side=tk.RIGHT, fill=tk.Y)
        ent_lb.config(yscrollcommand=sb1.set)
        
        sorted_ents = sorted(entity_counts.items())
        total_ents = sum(entity_counts.values())
        for etype, count in sorted_ents:
            ent_lb.insert(tk.END, f"{etype}: {count}")
        
        tk.Label(dialog, text=f"Total Entities: {total_ents}").pack()

        # Paths section
        tk.Label(dialog, text="Paths", font=("tahoma", 10, "bold")).pack(pady=(20, 5))
        path_frame = tk.Frame(dialog)
        path_frame.pack(fill=tk.BOTH, expand=True, padx=10)
        
        path_lb = tk.Listbox(path_frame, font=("tahoma", 9))
        path_lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb2 = tk.Scrollbar(path_frame, command=path_lb.yview)
        sb2.pack(side=tk.RIGHT, fill=tk.Y)
        path_lb.config(yscrollcommand=sb2.set)
        
        for pname in sorted(path_names):
            path_lb.insert(tk.END, pname)
            
        tk.Label(dialog, text=f"Total Paths: {len(path_names)}").pack(pady=(0, 10))

    def show_bulk_replace_entities(self):
        if not self.level_data:
            messagebox.showinfo("Wait", "Please load a level first.")
            return

        if self.preview_mode.get():
            messagebox.showwarning("Preview Mode", "Bulk replacing entities is disabled in Preview Mode.")
            return

        # Get list of entity types currently in the level
        current_types = set()
        for layer in self.level_data.get('layers', []):
            for ent in layer.get('entities', []):
                if ent.get('type'):
                    current_types.add(ent['type'])
        
        sorted_current = sorted(list(current_types))
        if not sorted_current:
            messagebox.showinfo("Wait", "This level has no entities to replace.")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Bulk Replace Entity Type")
        dialog.geometry("400x250")
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="Replace all instances of one entity type with another.", font=("tahoma", 9, "bold")).pack(pady=10)

        frame = tk.Frame(dialog)
        frame.pack(padx=20, pady=10, fill=tk.X)

        tk.Label(frame, text="Find:").grid(row=0, column=0, sticky=tk.W, pady=5)
        old_type_var = tk.StringVar()
        old_combo = ttk.Combobox(frame, textvariable=old_type_var, values=sorted_current, state="readonly")
        old_combo.grid(row=0, column=1, sticky=tk.EW, padx=5)
        if sorted_current: old_combo.current(0)

        tk.Label(frame, text="Replace with:").grid(row=1, column=0, sticky=tk.W, pady=5)
        new_type_var = tk.StringVar()
        # Use globally discovered entity_types as options
        new_combo = ttk.Combobox(frame, textvariable=new_type_var, values=self.entity_types, state="readonly")
        new_combo.grid(row=1, column=1, sticky=tk.EW, padx=5)
        if self.entity_types:
            if sorted_current[0] in self.entity_types:
                new_combo.set(sorted_current[0])
            else:
                new_combo.current(0)

        frame.grid_columnconfigure(1, weight=1)

        def do_replace():
            old_name = old_type_var.get()
            new_name = new_type_var.get()

            if not old_name or not new_name:
                return
                
            if old_name == new_name:
                messagebox.showinfo("No Change", "Source and destination types are the same.")
                return

            self.push_state() # Save for undo

            count = 0
            for layer in self.level_data.get('layers', []):
                for ent in layer.get('entities', []):
                    if ent.get('type') == old_name:
                        ent['type'] = new_name
                        count += 1
            
            self.render_level()
            messagebox.showinfo("Success", f"Replaced {count} entities of type '{old_name}' with '{new_name}'.")
            dialog.destroy()

        btn_bar = tk.Frame(dialog)
        btn_bar.pack(side=tk.BOTTOM, fill=tk.X, pady=10)
        tk.Button(btn_bar, text="Replace All", command=do_replace, width=15, bg="#e1f5fe").pack(side=tk.RIGHT, padx=10)
        tk.Button(btn_bar, text="Cancel", command=dialog.destroy, width=10).pack(side=tk.RIGHT)

    def show_bulk_replace_tiles(self):
        if not self.level_data:
            messagebox.showinfo("Wait", "Please load a level first.")
            return

        if self.preview_mode.get():
            messagebox.showwarning("Preview Mode", "Bulk replacing tiles is disabled in Preview Mode.")
            return

        # Get list of types currently in the level
        current_types = []
        for tt in self.level_data.get('tileTypes', []):
            if tt.get('value'):
                current_types.append(tt['value'])
        
        if not current_types:
            messagebox.showinfo("Wait", "This level has no decoration tiles to replace.")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Bulk Replace Tile Type")
        dialog.geometry("400x250")
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="Replace all instances of one tile with another.", font=("tahoma", 9, "bold")).pack(pady=10)

        frame = tk.Frame(dialog)
        frame.pack(padx=20, pady=10, fill=tk.X)

        tk.Label(frame, text="Find:").grid(row=0, column=0, sticky=tk.W, pady=5)
        old_type_var = tk.StringVar()
        old_combo = ttk.Combobox(frame, textvariable=old_type_var, values=current_types, state="readonly")
        old_combo.grid(row=0, column=1, sticky=tk.EW, padx=5)
        if current_types: old_combo.current(0)

        tk.Label(frame, text="Replace with:").grid(row=1, column=0, sticky=tk.W, pady=5)
        new_type_var = tk.StringVar()
        # Use globally discovered tile_types as options
        new_combo = ttk.Combobox(frame, textvariable=new_type_var, values=self.tile_types, state="readonly")
        new_combo.grid(row=1, column=1, sticky=tk.EW, padx=5)
        if self.tile_types:
            # Try to match current if possible
            if current_types[0] in self.tile_types:
                new_combo.set(current_types[0])
            else:
                new_combo.current(0)

        frame.grid_columnconfigure(1, weight=1)

        def do_replace():
            old_name = old_type_var.get()
            new_name = new_type_var.get()

            if not old_name or not new_name:
                return
                
            if old_name == new_name:
                messagebox.showinfo("No Change", "Source and destination types are the same.")
                return

            self.push_state() # Save for undo

            # 1. Ensure new_name is in level_data['tileTypes']
            tile_types = self.level_data.get('tileTypes', [])
            new_idx = -1
            for i, tt in enumerate(tile_types):
                if tt.get('value') == new_name:
                    new_idx = i
                    break
            
            if new_idx == -1:
                tile_types.append({'value': new_name})
                new_idx = len(tile_types) - 1
                self.level_data['tileTypeCount'] = len(tile_types)

            # 2. Find old index
            old_idx = -1
            for i, tt in enumerate(tile_types):
                if tt.get('value') == old_name:
                    old_idx = i
                    break

            # 3. Iterate through all decorations in all layers
            count = 0
            for layer in self.level_data.get('layers', []):
                for deco in layer.get('decorations', []):
                    if deco.get('cell') == old_idx:
                        deco['cell'] = new_idx
                        count += 1
            
            self.render_level()
            messagebox.showinfo("Success", f"Replaced {count} decorations of type '{old_name}' with '{new_name}'.")
            dialog.destroy()

        btn_bar = tk.Frame(dialog)
        btn_bar.pack(side=tk.BOTTOM, fill=tk.X, pady=10)
        tk.Button(btn_bar, text="Replace All", command=do_replace, width=15, bg="#e1f5fe").pack(side=tk.RIGHT, padx=10)
        tk.Button(btn_bar, text="Cancel", command=dialog.destroy, width=10).pack(side=tk.RIGHT)

    def render_level(self):
        if not self.level_data:
            self.canvas.delete("all")
            return

        self.canvas.delete("all")
        self.item_data_map = {}
        self.item_to_obj = {}
        
        # Performance: Cache canvas methods and set up drawing helpers
        create_oval = self.canvas.create_oval
        create_line = self.canvas.create_line
        create_rect = self.canvas.create_rectangle
        create_text = self.canvas.create_text

        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        
        center_x = width / 2 + self.offset_x
        center_y = height / 2 + self.offset_y
        scale = 5.0 * self.scale 

        # Culling bounds (wider for better panning feel)
        margin = 150
        canv_l, canv_t = -margin, -margin
        canv_r, canv_b = width + margin, height + margin

        # Track drawn clusters to reduce object count (LOD)
        # We use a grid size that changes with zoom - much more aggressive when zoomed out
        # This prevents tens of thousands of red rectangles from being created
        grid_size = 1 if self.scale > 0.4 else (4 if self.scale > 0.1 else 12)
        drawn_entities = set()
        drawn_decorations = set()
        
        if self.bounds:
            l, t, r, b = self.bounds
            x1, y1 = center_x + l * scale, center_y + t * scale
            x2, y2 = center_x + r * scale, center_y + b * scale
            create_rect(x1, y1, x2, y2, outline="black", dash=(4, 4), tags="bounds")
            create_text(x1, y1-10, text="Level Bounds", anchor=tk.SW, fill="grey")

        wall_count, ent_count, deco_count, path_count = 0, 0, 0, 0
        ent_scale_factor = self.ent_scale_var.get()
        
        # Pre-calculate selection IDs for performance
        selected_ids = {id(obj) for obj in self.selection}

        for i, layer in enumerate(self.level_data.get('layers', [])):
            vis = self.visibility.get(i, {})
            
            # Render Walls (as small rectangles, faster than circles)
            walls = layer.get('walls', [])
            wall_count += len(walls)
            if vis.get("walls") and vis["walls"].get():
                for wall in walls:
                    x = center_x + wall['pos_x'] * scale
                    y = center_y + wall['pos_y'] * scale
                    if canv_l < x < canv_r and canv_t < y < canv_b:
                        is_sel = id(wall) in selected_ids
                        color = "yellow" if is_sel else "blue"
                        width = 2 if is_sel else 1
                        id_wall = create_rect(x-3, y-3, x+3, y+3, fill=color, outline=color, width=width, tags="wall")
                        self.item_data_map[id_wall] = wall

            # Render Entities (Red)
            entities = layer.get('entities', [])
            ent_count += len(entities)
            if vis.get("entities") and vis["entities"].get():
                for ent in entities:
                    pos = ent['position']
                    x = center_x + pos[0] * scale * ent_scale_factor
                    y = center_y + pos[1] * scale * ent_scale_factor
                    
                    if canv_l < x < canv_r and canv_t < y < canv_b:
                        gx, gy = int(x/grid_size), int(y/grid_size)
                        is_sel = id(ent) in selected_ids
                        if (gx, gy) not in drawn_entities or is_sel:
                            outline = "yellow" if is_sel else "black"
                            width = 2 if is_sel else 1
                            id_ent = create_rect(x-6, y-6, x+6, y+6, fill="red", outline=outline, width=width, tags="entity")
                            self.item_data_map[id_ent] = ent
                            if not is_sel: drawn_entities.add((gx, gy))

            # Render Decorations (Green)
            decorations = layer.get('decorations', [])
            deco_count += len(decorations)
            if vis.get("decorations") and vis["decorations"].get():
                for deco in decorations:
                    pos = deco['position']
                    x = center_x + pos[0] * scale
                    y = center_y + pos[1] * scale
                    
                    if canv_l < x < canv_r and canv_t < y < canv_b:
                        gx, gy = int(x/grid_size), int(y/grid_size)
                        is_sel = id(deco) in selected_ids
                        if (gx, gy) not in drawn_decorations or is_sel:
                            outline = "yellow" if is_sel else ""
                            width = 2 if is_sel else 1
                            id_deco = create_rect(x-3, y-3, x+3, y+3, fill="green", outline=outline, width=width, tags="decoration")
                            self.item_data_map[id_deco] = deco
                            if not is_sel: drawn_decorations.add((gx, gy))

            # Render Paths (Optimized poly-line rendering)
            paths = layer.get('paths', [])
            path_count += len(paths)
            if vis.get("paths") and vis["paths"].get():
                steps = 5 if self.scale < 1.0 else 10 # LOD for splines
                for path in paths:
                    if path.get('path_flag') == 1:
                        points = path.get('spline_points', [])
                        all_coords = []
                        for pt in points:
                            p0, p1, p2 = pt['p0'], pt['p1'], pt['p2']
                            # Culling: only calculate if start point is near view
                            if canv_l-500 < (center_x + p0[0]*scale) < canv_r+500:
                                seg_pts = self.get_bezier_points(p0, p1, p2, center_x, center_y, scale, steps)
                                if all_coords:
                                    all_coords.extend(seg_pts[2:]) # Skip first point of segment (already added)
                                else:
                                    all_coords.extend(seg_pts)
                        
                        if all_coords:
                            path_id = create_line(*all_coords, fill="purple", width=2, tags="path")
                            self.item_data_map[path_id] = path

        # Render GooStarts (Yellow) from XML
        for i, gs in enumerate(self.goostarts):
            gs_x, gs_y = gs['pos']
            x = center_x + gs_x * scale
            y = center_y + gs_y * scale
            if canv_l < x < canv_r and canv_t < y < canv_b:
                tag = f"gs_{i}"
                # Use the actual data reference to allow persistent selection
                gs_data = gs['data']
                is_sel = id(gs_data) in selected_ids
                
                # Use two solid ovals to simulate an outline without using 'outline' parameter
                # Use 'red' for selected GooStart highlight
                id_border = create_oval(x-9, y-9, x+9, y+9, fill="red" if is_sel else "orange", outline="", tags=("goostart", tag))
                id_back = create_oval(x-7, y-7, x+7, y+7, fill="yellow", outline="", tags=("goostart", tag))
                id_text = create_text(x, y, text="G", fill="black", font=("tahoma", "8", "bold"), tags=("goostart", tag))
                
                self.item_data_map[id_border] = gs_data
                self.item_data_map[id_back] = gs_data
                self.item_data_map[id_text] = gs_data
                # Store the reference to the gs dict for updating
                self.item_to_obj[id_border] = gs
                self.item_to_obj[id_back] = gs
                self.item_to_obj[id_text] = gs

        self.status_var.set(f"File: {os.path.basename(self.current_file) if self.current_file else 'None'} | "
                           f"Walls: {wall_count} | Entities: {ent_count} | "
                           f"Decorations: {deco_count} | Paths: {path_count}")

    def get_bezier_points(self, p0, p1, p2, cx, cy, s, steps):
        pts = []
        for i in range(steps + 1):
            t = i / steps
            qx = (1-t)**2 * p0[0] + 2*(1-t)*t * p1[0] + t**2 * p2[0]
            qy = (1-t)**2 * p0[1] + 2*(1-t)*t * p1[1] + t**2 * p2[1]
            pts.append(cx + qx * s)
            pts.append(cy + qy * s)
        return pts

    # Optimized Pan and Zoom
    def on_left_click_press(self, event):
        self.canvas.focus_set() # Take focus away from dropdowns/entry widgets
        self.last_x = event.x
        self.last_y = event.y
        self.is_dragging = False
        self.selection_start = (event.x, event.y)

        if self.preview_mode.get():
            return

        # Check modifiers for multi-select (Shift, Alt, or Control)
        shift_held = (event.state & 0x1) != 0
        control_held = (event.state & 0x4) != 0
        alt_held = (event.state & 0x20000) != 0 or (event.state & 0x8) != 0
        multi_select = shift_held or control_held or alt_held

        # Check for items to drag
        items = self.canvas.find_overlapping(event.x-3, event.y-3, event.x+3, event.y+3)
        found_obj = None
        if items:
            for item_id in reversed(items):
                tags = self.canvas.gettags(item_id)
                if "path" in tags:
                    continue # Paths are not draggable
                    
                if item_id in self.item_data_map:
                    data = self.item_data_map[item_id]
                    # Check if it's an editable GooStart
                    if data.get("type") == "GooStart" and data.get("source") == "Multilevel XML":
                        continue # Skip multilevel goostarts as they are read-only
                    
                    found_obj = data
                    break

        if found_obj:
            if multi_select:
                # Toggle selection
                if id(found_obj) in [id(o) for o in self.selection]:
                    self.selection = [o for o in self.selection if o is not found_obj]
                else:
                    self.selection.append(found_obj)
            else:
                # Normal click: if clicking outside current selection, reset it
                if id(found_obj) not in [id(o) for o in self.selection]:
                    self.selection = [found_obj]
            
            if self.selection:
                self.is_dragging = True
                self.push_state() # Save state before moving
                
                self.render_level() # Update highlights (RECREATES IDs)
                
                # Performance optimization: pre-calculate IDs for dragging AFTER RENDER
                sel_ids = {id(o) for o in self.selection}
                self.dragging_targets = []
                seen_targets = set()
                for cid, data in self.item_data_map.items():
                    if id(data) in sel_ids:
                        tags = self.canvas.gettags(cid)
                        group_tag = next((t for t in tags if t.startswith("gs_")), None)
                        target = group_tag if group_tag else cid
                        if target not in seen_targets:
                            self.dragging_targets.append(target)
                            seen_targets.add(target)
                            self.canvas.tag_raise(target)
        else:
            if not multi_select:
                self.selection = []
                self.render_level()

    def on_left_click_move(self, event):
        dx = event.x - self.last_x
        dy = event.y - self.last_y
        
        if self.is_dragging and self.selection:
            # Move all selected items via pre-calculated targets
            for target in getattr(self, 'dragging_targets', []):
                self.canvas.move(target, dx, dy)
        elif self.selection_start and not self.is_dragging:
            # Box selection
            if self.selection_rect:
                self.canvas.delete(self.selection_rect)
            
            x1, y1 = self.selection_start
            x2, y2 = event.x, event.y
            self.selection_rect = self.canvas.create_rectangle(x1, y1, x2, y2, outline="grey", dash=(4,4), tags="selection_box")
            
        self.last_x = event.x
        self.last_y = event.y

    def on_left_click_release(self, event):
        if self.is_dragging and self.selection:
            # Update all selected objects
            sel_ids = {id(o) for o in self.selection}
            updated_objs = set()

            for cid, data in self.item_data_map.items():
                if id(data) in sel_ids and id(data) not in updated_objs:
                    self.update_object_position(cid)
                    updated_objs.add(id(data))
                    
            self.is_dragging = False
            self.dragging_targets = []
            self.render_level()
        elif self.selection_start:
            if self.selection_rect:
                coords = self.canvas.coords(self.selection_rect)
                self.canvas.delete(self.selection_rect)
                self.selection_rect = None
                
                # Area-based select
                items = self.canvas.find_enclosed(*coords)
                new_items = []
                for item_id in items:
                    if item_id in self.item_data_map:
                        data = self.item_data_map[item_id]
                        if id(data) not in [id(o) for o in new_items]:
                            new_items.append(data)
                
                shift_held = (event.state & 0x1) != 0
                control_held = (event.state & 0x4) != 0
                alt_held = (event.state & 0x20000) != 0 or (event.state & 0x8) != 0
                
                if shift_held or control_held or alt_held:
                    for item in new_items:
                        if id(item) not in [id(o) for o in self.selection]:
                            self.selection.append(item)
                else:
                    self.selection = new_items
                
                self.render_level()
            
        self.selection_start = None

    def copy_selected(self, event=None):
        if self.preview_mode.get(): 
            return

        # Use current selection OR item under mouse
        targets = self.selection
        if not targets:
            # Check under mouse
            pointer_x = self.canvas.winfo_pointerx() - self.canvas.winfo_rootx()
            pointer_y = self.canvas.winfo_pointery() - self.canvas.winfo_rooty()
            items = self.canvas.find_overlapping(pointer_x-3, pointer_y-3, pointer_x+3, pointer_y+3)
            if items:
                for item_id in reversed(items):
                    if item_id in self.item_data_map:
                        targets = [self.item_data_map[item_id]]
                        break

        if targets:
            clipboard_data = []
            
            avg_x, avg_y = 0.0, 0.0
            valid_objs = []
            ent_scale = self.ent_scale_var.get()
            
            for obj in targets:
                # Find type and pos
                obj_type = None
                iwu_x, iwu_y = 0.0, 0.0
                
                if 'pos_x' in obj: # Wall
                    obj_type = "wall"
                    iwu_x, iwu_y = obj['pos_x'], obj['pos_y']
                elif 'position' in obj: # Ent/Deco
                    obj_type = "entity" if 'vec' in obj else "decoration"
                    if obj_type == "entity":
                        iwu_x, iwu_y = obj['position'][0] * ent_scale, obj['position'][1] * ent_scale
                    else:
                        iwu_x, iwu_y = obj['position'][0], obj['position'][1]
                
                if obj_type:
                    valid_objs.append({
                        'type': obj_type,
                        'data': copy.deepcopy(obj),
                        'iwu_pos': (iwu_x, iwu_y)
                    })
                    avg_x += iwu_x
                    avg_y += iwu_y
            
            if valid_objs:
                avg_x /= len(valid_objs)
                avg_y /= len(valid_objs)
                
                # Store relative offsets from selection center in IWU
                for item in valid_objs:
                    item['offset'] = (item['iwu_pos'][0] - avg_x, item['iwu_pos'][1] - avg_y)
                
                self.clipboard = {
                    'mode': 'multi' if len(valid_objs) > 1 else 'single',
                    'items': valid_objs
                }
                self.status_var.set(f"Copied {len(valid_objs)} items.")
            else:
                self.status_var.set("No valid items to copy.")

    def paste_item(self, event=None, canvas_x=None, canvas_y=None):
        if self.preview_mode.get(): 
            return
        if not self.clipboard or not self.level_data:
            return

        try:
            self.push_state()
            
            # Calculate base position in world coordinates (IWU)
            width = self.canvas.winfo_width()
            height = self.canvas.winfo_height()
            scale = 5.0 * self.scale
            center_x = width / 2 + self.offset_x
            center_y = height / 2 + self.offset_y
            ent_scale = self.ent_scale_var.get()

            if canvas_x is None or canvas_y is None:
                pointer_x = self.canvas.winfo_pointerx() - self.canvas.winfo_rootx()
                pointer_y = self.canvas.winfo_pointery() - self.canvas.winfo_rooty()
                if not (0 <= pointer_x <= width and 0 <= pointer_y <= height):
                    pointer_x, pointer_y = width/2, height/2
                canvas_x, canvas_y = pointer_x, pointer_y

            # Base world coordinates for the paste 'center'
            base_iwu_x = (canvas_x - center_x) / scale
            base_iwu_y = (canvas_y - center_y) / scale
            
            new_selection = []
            ent_scale = self.ent_scale_var.get()
            
            for item in self.clipboard.get('items', []):
                new_data = copy.deepcopy(item['data'])
                obj_type = item['type']
                off_x, off_y = item['offset']
                
                # New world position (IWU)
                target_iwu_x = base_iwu_x + off_x
                target_iwu_y = base_iwu_y + off_y

                if obj_type == "entity":
                    new_data['position'] = [target_iwu_x / ent_scale, target_iwu_y / ent_scale]
                elif obj_type == "wall":
                    new_data['pos_x'] = target_iwu_x
                    new_data['pos_y'] = target_iwu_y
                    # Assign new unique wall_id
                    max_id = 0
                    for layer in self.level_data.get('layers', []):
                        for wall in layer.get('walls', []):
                            max_id = max(max_id, wall.get('wall_id', 0))
                    new_data['wall_id'] = max_id + 1
                else: # decoration
                    new_data['position'] = [target_iwu_x, target_iwu_y]

                # Auto-find the best layer for this specific type (most crowded)
                layers = self.level_data.get('layers', [])
                type_to_key = {"entity": "entities", "wall": "walls", "decoration": "decorations"}
                list_key = type_to_key.get(obj_type, obj_type + "s")
                
                target_layer_idx = 0
                max_count = -1
                for idx, layer in enumerate(layers):
                    count = len(layer.get(list_key, []))
                    if count > max_count:
                        max_count = count
                        target_layer_idx = idx

                if 0 <= target_layer_idx < len(layers):
                    layers[target_layer_idx].setdefault(list_key, []).append(new_data)
                    new_selection.append(new_data)
            
            if new_selection:
                self.selection = new_selection
                self.render_level()
                self.status_var.set(f"Pasted {len(new_selection)} items.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to paste: {e}")
            import traceback
            traceback.print_exc()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to paste: {e}")

    def on_right_click_press(self, event):
        self.canvas.focus_set() # Take focus away from entries/dropdowns
        self.last_x = event.x
        self.last_y = event.y
        self.panning = True
        self.right_click_moved = False
        
        # New context menu support for empty canvas (Paste)
        self.right_click_event = event

    def on_right_click_move(self, event):
        dx = event.x - self.last_x
        dy = event.y - self.last_y
        
        if abs(dx) > 2 or abs(dy) > 2:
            self.right_click_moved = True

        if self.panning:
            self.offset_x += dx
            self.offset_y += dy
            # Use move() instead of full re-render for smooth panning
            self.canvas.move("all", dx, dy)
            
        self.last_x = event.x
        self.last_y = event.y

    def on_right_click_release(self, event):
        if self.panning:
            self.panning = False
            # Full re-render on release to fix any culling issues
            self.render_level()
            
        # If the mouse didn't move much, treat it as a right-click for properties
        if not self.right_click_moved:
            self.on_right_click(event)

    def on_button_press(self, event):
        pass # Replaced by on_left_click_press/on_right_click_press

    def on_move_press(self, event):
        pass # Replaced by on_left_click_move/on_right_click_move

    def on_move_release(self, event):
        pass # Replaced by on_left_click_release/on_right_click_release

    def update_object_position(self, item_id):
        if item_id not in self.item_data_map:
            return
            
        data = self.item_data_map[item_id]
        coords = self.canvas.coords(item_id)
        
        # Determine center point based on shape type
        if len(coords) == 4:
            # For rectangles and ovals, coords are [x1, y1, x2, y2]. Center is (x1+x2)/2.
            cx = (coords[0] + coords[2]) / 2
            cy = (coords[1] + coords[3]) / 2
        elif len(coords) == 2:
            # For text items, coords are [x, y].
            cx = coords[0]
            cy = coords[1]
        else:
            return # Should not happen for draggable objects
        
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        center_x = width / 2 + self.offset_x
        center_y = height / 2 + self.offset_y
        scale = 5.0 * self.scale
        
        # Determine source type from tags
        tags = self.canvas.gettags(item_id)
        
        if "goostart" in tags:
            # GooStart (XML)
            new_x = (cx - center_x) / scale
            new_y = (cy - center_y) / scale
            if item_id in self.item_to_obj:
                gs_entry = self.item_to_obj[item_id]
                gs_entry['pos'] = (new_x, new_y)
                # Update tooltip data
                gs_entry['data']['x'] = str(new_x)
                gs_entry['data']['y'] = str(new_y)
                # Update XML element if it exists
                if 'element' in gs_entry:
                    gs_entry['element'].set('x', f"{new_x:e}")
                    gs_entry['element'].set('y', f"{new_y:e}")
                self.status_var.set(f"Updated GooStart to ({self.format_num(new_x)}, {self.format_num(new_y)})")
        elif "entity" in tags:
            ent_scale = self.ent_scale_var.get()
            new_x = (cx - center_x) / (scale * ent_scale)
            new_y = (cy - center_y) / (scale * ent_scale)
            data['position'] = [new_x, new_y]
            self.status_var.set(f"Updated Entity to ({self.format_num(new_x)}, {self.format_num(new_y)})")
        elif "decoration" in tags:
            new_x = (cx - center_x) / scale
            new_y = (cy - center_y) / scale
            data['position'] = [new_x, new_y]
            self.status_var.set(f"Updated Decoration to ({self.format_num(new_x)}, {self.format_num(new_y)})")
        elif "wall" in tags:
            new_x = (cx - center_x) / scale
            new_y = (cy - center_y) / scale
            data['pos_x'] = new_x
            data['pos_y'] = new_y
            self.status_var.set(f"Updated Wall to ({self.format_num(new_x)}, {self.format_num(new_y)})")

    def on_right_click(self, event):
        items = self.canvas.find_overlapping(event.x-3, event.y-3, event.x+3, event.y+3)
        if items:
            for item_id in reversed(items):
                if item_id in self.item_data_map:
                    data = self.item_data_map[item_id]
                    
                    # If clicking an item NOT in current selection, select it solely
                    if id(data) not in [id(o) for o in self.selection]:
                        self.selection = [data]
                        self.render_level()

                    tags = self.canvas.gettags(item_id)
                    
                    # Create a context menu
                    menu = tk.Menu(self.root, tearoff=0)
                    
                    # Check for editable status
                    is_multilevel_gs = "goostart" in tags and data.get("source") == "Multilevel XML"
                    preview = self.preview_mode.get()
                    multi = len(self.selection) > 1

                    if not multi:
                        # Single item menu
                        obj_to_edit = data
                        id_to_edit = item_id
                        gs_to_edit = self.item_to_obj.get(item_id) if "goostart" in tags else None

                        label = "View Properties (Read Only)" if is_multilevel_gs else "Edit Properties"
                        menu.add_command(label=label, 
                                         command=lambda: self.open_edit_dialog(obj_to_edit, id_to_edit, gs_to_edit))
                    else:
                        # Multi-item menu
                        menu.add_command(label=f"Selected {len(self.selection)} items", state="disabled")
                    
                    if not is_multilevel_gs:
                        menu.add_command(label=f"Copy Selection ({len(self.selection)})", command=self.copy_selected)
                        
                    if not preview and not is_multilevel_gs:
                        menu.add_separator()
                        del_label = "Delete Selection" if multi else "Delete"
                        menu.add_command(label=del_label, command=self.delete_selected)

                    if is_multilevel_gs and not multi:
                        menu.add_separator()
                        menu.add_command(label="Source: Multilevel XML", state="disabled")

                    menu.post(event.x_root, event.y_root)
                    self.context_menu = menu
                    return
        
        # If right clicked on empty space
        if not self.right_click_moved:
            menu = tk.Menu(self.root, tearoff=0)
            
            # Store coordinates
            right_x, right_y = event.x, event.y
            
            if not self.preview_mode.get():
                menu.add_command(label="Add Entity here (Ctrl+E)", command=lambda: self.add_entity(right_x, right_y))
                menu.add_command(label="Add Wall here (Ctrl+W)", command=lambda: self.add_wall(right_x, right_y))
                menu.add_command(label="Add Decoration here (Ctrl+D)", command=lambda: self.add_decoration(right_x, right_y))
                
                if self.clipboard:
                    menu.add_separator()
                    clip_count = len(self.clipboard.get('items', []))
                    label = f"Paste {clip_count} items (Ctrl+V)" if clip_count > 1 else f"Paste item (Ctrl+V)"
                    menu.add_command(label=label, command=lambda: self.paste_item(canvas_x=right_x, canvas_y=right_y))
            else:
                menu.add_command(label="Preview Mode: Creation Disabled", state="disabled")
                
            menu.post(event.x_root, event.y_root)
            self.context_menu = menu

    def delete_selected(self):
        if not self.selection:
            return
        
        preview = self.preview_mode.get()
        if preview:
            return

        count = len(self.selection)
        msg = f"Are you sure you want to delete {count} selected items?" if count > 1 else "Are you sure you want to delete this item?"
        
        if messagebox.askyesno("Confirm Delete", msg):
            self.push_state()
            
            sel_ids = [id(o) for o in self.selection]
            
            for layer in self.level_data.get('layers', []):
                for key in ['entities', 'walls', 'decorations']:
                    if key in layer:
                        layer[key] = [obj for obj in layer[key] if id(obj) not in sel_ids]
            
            self.selection = []
            self.render_level()
            self.status_var.set(f"Deleted {count} items.")

    def on_delete_key(self, event):
        if self.preview_mode.get():
            return

        if self.selection:
            self.delete_selected()
            return

        # Fallback to item under mouse if nothing selected
        items = self.canvas.find_overlapping(event.x-3, event.y-3, event.x+3, event.y+3)
        if not items:
            return
            
        for item_id in reversed(items):
            if item_id in self.item_data_map:
                data = self.item_data_map[item_id]
                self.selection = [data]
                self.delete_selected()
                break

    def open_edit_dialog(self, data, item_id, gs_entry=None):
        preview = self.preview_mode.get()
        dialog = tk.Toplevel(self.root)
        dialog.title("Edit Properties" if not preview else "View Properties (Preview Mode)")
        dialog.geometry("400x500")
        
        # Use a scrollable frame for many properties
        main_frame = tk.Frame(dialog)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        canvas = tk.Canvas(main_frame)
        scrollbar = tk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas)
        
        scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        frame_id = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        
        # This ensures the internal frame expands to the canvas width
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(frame_id, width=e.width))
        
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        entries = {}
        advanced_data = {} # To store keys of complex data for special handling
        
        for k, v in data.items():
            if k in ['shapes', 'spline_points', 'source', 'note']:
                continue
            
            # Use 'advanced' grouping for dictionaries or lists that aren't coords
            is_advanced = isinstance(v, dict) or (isinstance(v, list) and k not in ['position', 'bounds', 'rgba', 'color_rgba'])
            
            row = len(entries)
            
            # Special handling for Decoration Tile Type (cell)
            if k == 'cell' and "decoration" in self.canvas.gettags(item_id):
                tk.Label(scroll_frame, text="tile_type").grid(row=row, column=0, padx=5, pady=2, sticky=tk.W)
                current_type = "Unknown"
                if 0 <= v < len(self.level_data.get('tileTypes', [])):
                    current_type = self.level_data['tileTypes'][v].get('value', 'Unknown')
                
                entry = ttk.Combobox(scroll_frame, values=self.tile_types, state="readonly" if not preview else "disabled")
                entry.set(current_type)
                scroll_frame.grid_columnconfigure(1, weight=1)
                entry.grid(row=row, column=1, padx=5, pady=2, sticky=tk.EW)
                entries[k] = entry
                continue

            tk.Label(scroll_frame, text=k, fg="blue" if is_advanced else "black").grid(row=row, column=0, padx=5, pady=2, sticky=tk.W)
            
            scroll_frame.grid_columnconfigure(1, weight=1)
            
            # Special handling for Entity Type dropdown
            if k == 'type' and "entity" in self.canvas.gettags(item_id):
                # Using readonly state to prevent typing errors and satisfy game constraints.
                # Users can still use the arrow to select or press letters to jump to items.
                entry = ttk.Combobox(scroll_frame, values=self.entity_types, state="readonly" if not preview else "disabled")
                entry.set(str(v))
                entry.grid(row=row, column=1, padx=5, pady=2, sticky=tk.EW)
                entries[k] = entry
            else:
                entry = tk.Entry(scroll_frame, state="normal" if not preview else "readonly")
                # For dicts/lists, use json.dumps for easier editing
                if is_advanced:
                    entry.insert(0, json.dumps(v))
                    advanced_data[k] = True
                else:
                    entry.insert(0, str(v))
                
            entry.grid(row=row, column=1, padx=5, pady=2, sticky=tk.EW)
            entries[k] = entry
            
        def save_changes():
            # Validation
            tags = self.canvas.gettags(item_id)
            if "entity" in tags:
                type_entry = entries.get('type')
                if type_entry and type_entry.get().strip().upper() == "CHANGEME":
                    messagebox.showerror("Error", "You must change the entity type from 'CHANGEME' before saving.")
                    return

            self.push_state() # Save state before applying changes
            for k, entry in entries.items():
                new_val = entry.get()
                
                # Special handling for decoration tile type (cell)
                if k == 'cell' and "decoration" in tags:
                    new_tile_type = new_val
                    # Find index in existing tileTypes
                    tile_types = self.level_data.setdefault('tileTypes', [])
                    found_idx = -1
                    for i, tt in enumerate(tile_types):
                        if tt.get('value') == new_tile_type:
                            found_idx = i
                            break
                    
                    if found_idx == -1:
                        # Add new tile type to level metadata
                        tile_types.append({'value': new_tile_type})
                        found_idx = len(tile_types) - 1
                        self.level_data['tileTypeCount'] = len(tile_types)
                        print(f"Added new tile type to level: {new_tile_type}")
                    
                    data[k] = found_idx
                    continue

                orig_v = data[k]
                
                try:
                    if k in advanced_data:
                        # Parse complex types back as JSON
                        data[k] = json.loads(new_val)
                    elif isinstance(orig_v, int):
                        data[k] = int(new_val)
                    elif isinstance(orig_v, float):
                        data[k] = float(new_val)
                    elif isinstance(orig_v, list):
                        data[k] = json.loads(new_val)
                    else:
                        data[k] = new_val
                except Exception as e:
                    # If parsing fails, revert or keep as string depending on importance
                    if k in advanced_data:
                        messagebox.showerror("Parse Error", f"Invalid JSON for {k}. Field not updated.\nError: {e}")
                    else:
                        data[k] = new_val
                
                # If this is a GooStart with an XML element, sync it back
                if gs_entry and 'element' in gs_entry:
                    if k in ['x', 'y', 'area']:
                        try:
                            f_val = float(new_val)
                            gs_entry['element'].set(k, f"{f_val:e}")
                        except:
                            gs_entry['element'].set(k, new_val)
                    else:
                        gs_entry['element'].set(k, new_val)
            
            dialog.destroy()
            self.render_level()
            self.status_var.set("Properties updated.")

        def delete_item():
            tags = self.canvas.gettags(item_id)
            if "entity" in tags:
                if messagebox.askyesno("Confirm Delete", "Are you sure you want to delete this entity?"):
                    self.push_state() # Save before delete
                    # Find and remove from level_data
                    removed = False
                    for layer in self.level_data.get('layers', []):
                        entities = layer.get('entities', [])
                        if data in entities:
                            entities.remove(data)
                            removed = True
                            break
                    
                    if removed:
                        dialog.destroy()
                        self.render_level()
                        self.status_var.set("Entity deleted.")
            elif "wall" in tags:
                if messagebox.askyesno("Confirm Delete", "Are you sure you want to delete this wall?"):
                    self.push_state() # Save before delete
                    # Find and remove from level_data
                    removed = False
                    for layer in self.level_data.get('layers', []):
                        walls = layer.get('walls', [])
                        if data in walls:
                            walls.remove(data)
                            removed = True
                            break
                    
                    if removed:
                        dialog.destroy()
                        self.render_level()
                        self.status_var.set("Wall deleted.")
            elif "decoration" in tags:
                if messagebox.askyesno("Confirm Delete", "Are you sure you want to delete this decoration?"):
                    self.push_state() # Save before delete
                    # Find and remove from level_data
                    removed = False
                    for layer in self.level_data.get('layers', []):
                        decorations = layer.get('decorations', [])
                        if data in decorations:
                            decorations.remove(data)
                            removed = True
                            break
                    
                    if removed:
                        dialog.destroy()
                        self.render_level()
                        self.status_var.set("Decoration deleted.")

        btn_frame = tk.Frame(dialog)
        btn_frame.pack(fill=tk.X)
        
        # Add Delete button for entities, walls, or decorations
        tags = self.canvas.gettags(item_id)
        if not preview:
            if "entity" in tags:
                tk.Button(btn_frame, text="Delete Entity", fg="white", bg="red", command=delete_item).pack(side=tk.LEFT, padx=5, pady=5)
            elif "wall" in tags:
                tk.Button(btn_frame, text="Delete Wall", fg="white", bg="red", command=delete_item).pack(side=tk.LEFT, padx=5, pady=5)
            elif "decoration" in tags:
                tk.Button(btn_frame, text="Delete Decoration", fg="white", bg="red", command=delete_item).pack(side=tk.LEFT, padx=5, pady=5)

            tk.Button(btn_frame, text="Save", command=save_changes).pack(side=tk.RIGHT, padx=5, pady=5)
        else:
            tk.Label(btn_frame, text="Preview Mode Active (Read-Only)", fg="red", font=("tahoma", 8, "bold")).pack(side=tk.LEFT, padx=10)

        tk.Button(btn_frame, text="Close" if preview else "Cancel", command=dialog.destroy).pack(side=tk.RIGHT, padx=5, pady=5)

    def reset_view(self):
        self.scale = 1.0
        self.offset_x = 0
        self.offset_y = 0
        self.render_level()

    def zoom(self, event):
        # Zoom centered on mouse position
        old_scale = self.scale
        if event.delta > 0:
            self.scale *= 1.2
        else:
            self.scale /= 1.2
            
        # Constrain scale
        self.scale = max(0.01, min(self.scale, 1000.0))
        
        mx, my = event.x, event.y
        cx = self.canvas.winfo_width() / 2
        cy = self.canvas.winfo_height() / 2
        
        px = (mx - cx - self.offset_x) / (5.0 * old_scale)
        py = (my - cy - self.offset_y) / (5.0 * old_scale)
        
        self.offset_x += px * (5.0 * old_scale - 5.0 * self.scale)
        self.offset_y += py * (5.0 * old_scale - 5.0 * self.scale)
        
        # Performance: Debounce full render during zoom
        if hasattr(self, '_zoom_job'):
            self.root.after_cancel(self._zoom_job)
        
        # Visual feedback: scale existing items temporarily
        ratio = self.scale / old_scale
        self.canvas.scale("all", mx, my, ratio, ratio)
        
        self._zoom_job = self.root.after(150, self.render_level)

if __name__ == "__main__":
    root = tk.Tk()
    app = LevelEditor(root)
    # Handle window resize to re-render
    root.bind("<Configure>", lambda e: app.render_level() if app.level_data else None)
    root.mainloop()
