import json
import os

def sort_and_format_mapping(file_path):
    """
    Reads a JSON file, sorts the 'team_names' and 'league_names' dictionaries
    by their values (Display Name), and writes the file back with custom formatting
    that adds blank lines between groups of different Display Names.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error reading file: {e}")
        return

    def format_dict_with_grouping(d, indent_level=2):
        if not d:
            return "{}"
        
        # Sort by value (display name), then by key
        # Case-insensitive sorting for better grouping
        sorted_items = sorted(d.items(), key=lambda x: (str(x[1]).lower(), str(x[0]).lower()))
        
        lines = []
        lines.append("{\n")
        
        prev_value = None
        indent = " " * (indent_level * 2)
        
        for i, (k, v) in enumerate(sorted_items):
            # Check for grouping change
            # We compare lowercased values to group case-insensitive variants together if they map to the same display name
            current_val_lower = str(v).lower()
            if prev_value is not None and current_val_lower != prev_value:
                lines.append("\n") # Add blank line between groups
            
            # Use json.dumps to handle escaping of keys and values safely
            key_str = json.dumps(k, ensure_ascii=False)
            val_str = json.dumps(v, ensure_ascii=False)
            
            line = f'{indent}{key_str}: {val_str}'
            
            # Add comma if not the last item
            if i < len(sorted_items) - 1:
                line += ","
            
            lines.append(line + "\n")
            
            prev_value = current_val_lower
            
        lines.append(" " * ((indent_level - 1) * 2) + "}")
        return "".join(lines)

    # Reconstruct the JSON string manually to preserve order and add custom formatting
    output_lines = []
    output_lines.append("{\n")
    
    # Define preferred order for top-level keys
    keys_order = ["_comment", "_usage", "team_names", "league_names"]
    
    # Add any other keys that might exist in the data but aren't in our explicit list
    existing_keys = list(data.keys())
    for k in existing_keys:
        if k not in keys_order:
            keys_order.append(k)
            
    # Filter keys that actually exist in the data
    keys_to_write = [k for k in keys_order if k in data]
    
    for i, key in enumerate(keys_to_write):
        val = data[key]
        
        output_lines.append(f'  "{key}": ')
        
        if key == "team_names" or key == "league_names":
            formatted_dict = format_dict_with_grouping(val, indent_level=2)
            output_lines.append(formatted_dict)
        else:
            # For simple strings or other types, use standard json dump
            output_lines.append(json.dumps(val, ensure_ascii=False))
            
        if i < len(keys_to_write) - 1:
            output_lines.append(",\n")
        else:
            output_lines.append("\n")
            
    output_lines.append("}\n")
    
    output_str = "".join(output_lines)
    
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(output_str)
        print(f"Successfully sorted and formatted {file_path}")
    except Exception as e:
        print(f"Error writing file: {e}")

if __name__ == "__main__":
    # Use the absolute path provided in the user context
    file_path = r"d:\Sendy\govoet\script\gvtsch\manual_mapping.json"
    if os.path.exists(file_path):
        sort_and_format_mapping(file_path)
    else:
        print(f"File not found: {file_path}")
