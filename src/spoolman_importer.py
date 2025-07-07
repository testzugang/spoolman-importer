#!/usr/bin/env python3
"""
Spoolman Receipt Importer
Extracts filament data from PDF receipts and imports to Spoolman via API
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from pypdf import PdfReader
import requests
from openai import OpenAI


class SpoolmanImporter:
    def __init__(self, spoolman_url: str, openai_api_key: str = None):
        self.spoolman_url = spoolman_url.rstrip('/')
        self.client = OpenAI(api_key=openai_api_key) if openai_api_key else None
        self.vendor_data = self.load_vendor_data()
        self.color_data = self.load_color_data()

    def load_color_data(self) -> Dict:
        """Load color name to hex code mapping from JSON file."""
        try:
            script_dir = Path(__file__).parent
            color_data_path = script_dir / "resources" / "color-data.json"
            if color_data_path.exists():
                with open(color_data_path, 'r', encoding='utf-8') as file:
                    return json.load(file)
            else:
                print("Warning: Color data file not found. Hex codes will not be set.")
                return {"colors": {}}
        except Exception as e:
            print(f"Error loading color data: {e}")
            return {"colors": {}}


    def load_vendor_data(self) -> Dict:
        """Load vendor-specific filament data from JSON file"""
        try:
            # Construct path relative to this script's location
            script_dir = Path(__file__).parent
            vendor_data_path = script_dir / "resources" / "vendor-data.json"

            if vendor_data_path.exists():
                with open(vendor_data_path, 'r', encoding='utf-8') as file:
                    return json.load(file)
            else:
                print(f"Warning: Vendor data file not found at {vendor_data_path}")
                print("Using fallback defaults for spool weight and temperatures")
                return {"vendors": {}, "material_defaults": {}}
        except Exception as e:
            print(f"Error loading vendor data: {e}")
            return {"vendors": {}, "material_defaults": {}}

    def get_vendor_filament_data(self, brand: str, material: str, interactive: bool = True) -> Dict:
        """Get vendor-specific filament data (spool weight, temperatures)"""
        vendors = self.vendor_data.get("vendors", {})
        material_defaults = self.vendor_data.get("material_defaults", {})

        # Normalize brand and material names for matching
        brand_normalized = brand.strip().lower()
        material_normalized = material.upper().strip()

        vendor_data = None

        # Try exact brand match first
        if brand_normalized in (vendor.lower() for vendor in vendors):
            # Find the correct brand name with original casing
            for vendor_name_original in vendors:
                if vendor_name_original.lower() == brand_normalized:
                    brand_name_matched = vendor_name_original
                    break
            
            vendor_materials = vendors[brand_name_matched]

            # Try case-insensitive material match
            for vendor_material, data in vendor_materials.items():
                if vendor_material.lower() == material_normalized.lower():
                    vendor_data = data.copy()
                    break
            else:
                # Try partial material matches (e.g., "PLA Basic" matches "PLA")
                for vendor_material, data in vendor_materials.items():
                    if material_normalized.lower() in vendor_material.lower():
                        vendor_data = data.copy()
                        break

        # Try case-insensitive brand matching if no exact match
        if not vendor_data:
            for vendor_name, vendor_materials in vendors.items():
                if vendor_name.lower() == brand_normalized.lower():
                    # Try exact material match
                    if material_normalized in vendor_materials:
                        vendor_data = vendor_materials[material_normalized].copy()
                        break
                    else:
                        # Try partial material matches
                        for vendor_material, data in vendor_materials.items():
                            if material_normalized in vendor_material.upper():
                                vendor_data = data.copy()
                                break
                    if vendor_data:
                        break

        # Enrich vendor data with material defaults
        if vendor_data:
            base_material = self.extract_base_material(material_normalized)
            if base_material in material_defaults:
                # Add missing properties from material defaults
                defaults = material_defaults[base_material]
                for key, value in defaults.items():
                    if key not in vendor_data:
                        vendor_data[key] = value
            return vendor_data

        # No vendor-specific data found - handle interactively if possible
        if interactive:
            return self.handle_missing_vendor_data(brand, material, material_defaults)

        # Fall back to material defaults (non-interactive mode)
        base_material = self.extract_base_material(material_normalized)
        if base_material in material_defaults:
            return material_defaults[base_material].copy()

        # Ultimate fallback
        return {
            "density": 1.24,
            "spool_weight": 250,
            "extruder_temp": 220,
            "bed_temp": 60,
            "description": f"Default values for {brand} {material}"
        }

    def handle_missing_vendor_data(self, brand: str, material: str, material_defaults: Dict) -> Dict:
        """Handle case where vendor-specific data is not found"""
        print(f"\nWarning: No vendor data found for '{brand}' - '{material}'")

        # Show available vendors for debugging
        print("\nAvailable vendors in vendor-data.json:")
        for vendor_name in self.vendor_data.get("vendors", {}):
            print(f"  - {vendor_name}")

        # Show available material defaults
        print("\nAvailable default material types:")
        for i, (mat_type, data) in enumerate(material_defaults.items(), 1):
            density_info = f", density: {data.get('density', 'N/A')}" if 'density' in data else ""
            print(f"  {i}. {mat_type} (spool: {data['spool_weight']}g, "
                  f"ext: {data['extruder_temp']}°C, bed: {data['bed_temp']}°C{density_info})")

        print(f"\nOptions:")
        print("  r) Reload vendor-data.json file")
        print("  s) Stop import")
        print("  1-{}) Use material default".format(len(material_defaults)))

        while True:
            choice = input("\nChoose option [r/s/1-{}]: ".format(len(material_defaults))).strip().lower()

            if choice == 'r':
                print("Reloading vendor data...")
                self.vendor_data = self.load_vendor_data()
                # Retry with reloaded data (non-interactive to avoid infinite loop)
                return self.get_vendor_filament_data(brand, material, interactive=False)

            elif choice == 's':
                print("Import stopped by user")
                return None

            elif choice.isdigit():
                choice_num = int(choice)
                if 1 <= choice_num <= len(material_defaults):
                    selected_material = list(material_defaults.keys())[choice_num - 1]
                    selected_data = material_defaults[selected_material].copy()
                    selected_data["description"] = f"Using {selected_material} defaults for {brand} {material}"
                    print(f"Using {selected_material} defaults")
                    return selected_data

            print("Invalid choice. Please try again.")

    def extract_base_material(self, material: str) -> str:
        """Extract base material type from complex material names"""
        material_upper = material.upper()

        # Common material mappings
        if "PLA" in material_upper:
            return "PLA"
        elif "PETG" in material_upper:
            return "PETG"
        elif "ABS" in material_upper:
            return "ABS"
        elif "ASA" in material_upper:
            return "ASA"
        elif "TPU" in material_upper:
            return "TPU"
        elif "WOOD" in material_upper:
            return "WOOD"
        elif "SILK" in material_upper:
            return "SILK"
        else:
            return "PLA"  # Default fallback

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        """Extract text content from PDF file"""
        try:
            with open(pdf_path, 'rb') as file:
                pdf_reader = PdfReader(file)
                text = ""
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"
                return text
        except Exception as e:
            print(f"Error reading PDF: {e}")
            return ""

    def extract_filaments_with_llm(self, receipt_text: str) -> List[Dict]:
        """Use LLM to extract filament data from receipt text"""
        if not self.client:
            print("OpenAI client not configured. Please provide API key.")
            return []

        prompt = f"""
Extract 3D printer filament information from this receipt text. 
Return ONLY a JSON array of filament objects. Each object should have:
- brand: string (manufacturer name)
- material: string (PLA, PETG, ABS, etc.)
- color: string 
- diameter: number (1.75 or 3.0, default 1.75)
- weight: number (filament weight in grams, e.g. 1000 for 1kg)
- price: number (unit price)
- quantity: number (how many spools)
- spool_weight: number (optional, empty spool weight in grams, e.g. 200-250 for typical spools)

Only include items that are clearly 3D printer filaments. Ignore other products.
If information is missing, use reasonable defaults or null.
For spool_weight, only include if you can determine it from the receipt (rare), otherwise omit.

Receipt text:
{receipt_text}

JSON array:
"""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a data extraction assistant. Return only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1
            )

            result = response.choices[0].message.content.strip()
            # Clean up response - remove markdown formatting if present
            if result.startswith('```json'):
                result = result.replace('```json', '').replace('```', '')

            return json.loads(result)

        except Exception as e:
            print(f"LLM extraction error: {e}")
            return []

    def extract_filaments_pattern_matching(self, receipt_text: str) -> List[Dict]:
        """Fallback: Extract filaments using pattern matching"""
        filaments = []

        # Common filament patterns
        patterns = [
            r'(?i)(PLA|ABS|PETG|TPU|WOOD|SILK)\s+.*?(\d+(?:\.\d+)?)\s*(?:€|USD|\$|EUR)',
            r'(?i)filament.*?(PLA|ABS|PETG|TPU).*?(\d+(?:\.\d+)?)\s*(?:€|USD|\$|EUR)',
            r'(?i)(1\.75|3\.0).*?(PLA|ABS|PETG|TPU).*?(\d+(?:\.\d+)?)\s*(?:€|USD|\$|EUR)'
        ]

        for pattern in patterns:
            matches = re.findall(pattern, receipt_text)
            for match in matches:
                if len(match) >= 2:
                    filament = {
                        'brand': 'Unknown',
                        'material': match[0].upper() if match[0] else 'PLA',
                        'color': 'Unknown',
                        'diameter': 1.75,
                        'weight': 1000,  # Default 1kg
                        'price': float(match[-1]),
                        'quantity': 1
                    }
                    filaments.append(filament)

        return filaments

    def get_filaments(self) -> List[Dict]:
        """Get all existing filaments from Spoolman."""
        try:
            response = requests.get(f"{self.spoolman_url}/api/v1/filament")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error fetching existing filaments: {e}")
            return []

    def find_existing_filament(self, filament_data: Dict, vendor_id: int, existing_filaments: List[Dict]) -> Optional[Dict]:
        """Find a filament in a list of existing filaments."""
        filament_name = f"{filament_data['material']} {filament_data['color']}"
        for filament in existing_filaments:
            # Check for matching vendor ID and a case-insensitive name match
            if filament.get('vendor', {}).get('id') == vendor_id and filament['name'].lower() == filament_name.lower():
                return filament
        return None

    def get_vendors(self) -> List[Dict]:
        """Get available vendors from Spoolman"""
        try:
            response = requests.get(f"{self.spoolman_url}/api/v1/vendor")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error fetching vendors: {e}")
            return []

    def _generate_import_id(self, source_filename: str, filament_data: Dict, index: int) -> str:
        """Generate a unique ID for an imported spool."""
        item_key = f"{filament_data.get('brand')}-{filament_data.get('material')}-{filament_data.get('color')}-{filament_data.get('price')}"
        return f"imported_from:{Path(source_filename).name}|item:{item_key}|index:{index}"

    def get_spools_for_filament(self, filament_id: int) -> List[Dict]:
        """Get all spools for a given filament ID."""
        try:
            response = requests.get(f"{self.spoolman_url}/api/v1/spool?filament_id={filament_id}")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error fetching spools for filament {filament_id}: {e}")
            return []

    def import_filament(self, filament_data: Dict, vendor_id: int, existing_filaments: List[Dict], source_filename: str, interactive: bool = True) -> bool:
        """
        Imports a filament and its spools into Spoolman.
        Checks if the filament exists. If so, adds spools to it. If not, creates it first.
        """
        existing_filament = self.find_existing_filament(filament_data, vendor_id, existing_filaments)
        filament_id = None

        if existing_filament:
            filament_id = existing_filament['id']
            print(f"Found existing filament '{existing_filament['name']}' (ID: {filament_id}). Checking for new spools...")
        else:
            try:
                spoolman_data = {
                    "vendor_id": vendor_id,
                    "name": f"{filament_data['material']} {filament_data['color']}",
                    "material": filament_data.get('material'),
                    "color_hex": self.get_color_hex(filament_data['color'], interactive=interactive),
                    "diameter": filament_data['diameter'],
                    "weight": filament_data['weight'],
                    "price": filament_data.get('price'),
                    "density": filament_data.get('density') or self.get_material_density(filament_data['material']),
                    "comment": self.build_comment(filament_data)
                }
                spoolman_data = {k: v for k, v in spoolman_data.items() if v is not None}
                response = requests.post(f"{self.spoolman_url}/api/v1/filament", json=spoolman_data)
                response.raise_for_status()
                new_filament = response.json()
                filament_id = new_filament['id']
                existing_filaments.append(new_filament)
                print(f"Successfully created new filament '{spoolman_data['name']}' (ID: {filament_id})")
            except requests.exceptions.HTTPError as e:
                print(f"Error creating filament: {e.response.status_code} {e.response.reason}")
                try:
                    error_details = e.response.json()
                    print("  - API Response:", json.dumps(error_details, indent=2))
                except json.JSONDecodeError:
                    print("  - API Response (text):", e.response.text)
                return False
            except Exception as e:
                print(f"An unexpected error occurred during filament creation: {e}")
                return False

        try:
            existing_spools = self.get_spools_for_filament(filament_id)
            spools_created_count = 0
            for i in range(filament_data.get('quantity', 1)):
                import_id = self._generate_import_id(source_filename, filament_data, i)
                is_duplicate = any(import_id in spool.get('comment', '') for spool in existing_spools)

                if is_duplicate:
                    print(f"  - Skipping duplicate spool {i + 1}/{filament_data.get('quantity', 1)} (already imported).")
                    continue

                spool_data = {
                    "filament_id": filament_id,
                    "remaining_weight": filament_data['weight'],
                    "comment": self.build_comment(filament_data, import_id=import_id)
                }
                if filament_data.get('spool_weight'):
                    spool_data["spool_weight"] = filament_data['spool_weight']
                spool_response = requests.post(f"{self.spoolman_url}/api/v1/spool", json=spool_data)
                spool_response.raise_for_status()
                print(f"  - Created spool {i + 1}/{filament_data.get('quantity', 1)}")
                spools_created_count += 1
            return True # Return True even if no new spools were created
        except requests.exceptions.HTTPError as e:
            print(f"Error creating spool: {e.response.status_code} {e.response.reason}")
            try:
                error_details = e.response.json()
                print("  - API Response:", json.dumps(error_details, indent=2))
            except json.JSONDecodeError:
                print("  - API Response (text):", e.response.text)
            return False
        except Exception as e:
            print(f"An unexpected error occurred during spool creation: {e}")
            return False

    def create_vendor(self, name: str) -> Optional[int]:
        """Create a new vendor in Spoolman"""
        try:
            data = {"name": name}
            response = requests.post(f"{self.spoolman_url}/api/v1/vendor", json=data)
            response.raise_for_status()
            return response.json()['id']
        except Exception as e:
            print(f"Error creating vendor: {e}")
            return None

    def get_or_create_vendor(self, vendor_name: str) -> Optional[int]:
        """Get vendor ID or create new vendor"""
        vendors = self.get_vendors()

        # Check if vendor exists
        for vendor in vendors:
            if vendor['name'].lower() == vendor_name.lower():
                return vendor['id']

        # Create new vendor
        return self.create_vendor(vendor_name)

    def get_color_hex(self, color_name: str, interactive: bool = True) -> Optional[str]:
        """Find the hex code for a given color name, with interactive fallback."""
        if not color_name:
            return None
        
        colors = self.color_data.get("colors", {})
        
        # 1. Normalize the input color name (e.g., "Light Blue" -> "light-blue")
        normalized_color_name = color_name.lower().replace(" ", "-")

        # 2. Try for an exact match with the normalized name
        if normalized_color_name in colors:
            return colors[normalized_color_name]

        # 3. If no exact match, search for keywords in the normalized name
        #    (e.g., "galaxy-black" should match "black")
        for keyword in sorted(colors.keys(), key=len, reverse=True):
            if keyword in normalized_color_name:
                return colors[keyword]
        
        # 4. If still no match and interactive, ask the user
        if interactive:
            return self.handle_missing_color(color_name)
            
        return None

    def handle_missing_color(self, color_name: str) -> Optional[str]:
        """Handle case where a color name cannot be matched to a hex code."""
        print(f"\nWarning: No hex code found for color '{color_name}'")
        
        print("\nOptions:")
        print("  r) Reload color-data.json file")
        print("  m) Manually enter hex code (e.g., #FF0000)")
        print("  o) Omit color (will not be set in Spoolman)")
        print("  s) Stop import")

        while True:
            choice = input("\nChoose option [r/m/o/s]: ").strip().lower()

            if choice == 'r':
                print("Reloading color data...")
                self.color_data = self.load_color_data()
                return self.get_color_hex(color_name, interactive=False) # Retry non-interactively

            elif choice == 'm':
                while True:
                    hex_code = input("Enter hex code: ").strip()
                    if re.match(r'^#[0-9a-fA-F]{6}$', hex_code):
                        return hex_code
                    print("Invalid format. Please use #RRGGBB format.")

            elif choice == 'o':
                print("Omitting color for this filament.")
                return None
            
            elif choice == 's':
                print("Import stopped by user.")
                sys.exit(1)

            print("Invalid choice. Please try again.")

    def build_comment(self, filament_data: Dict, import_id: str = None) -> str:
        """Build comment field with temperature, vendor info, and an optional import ID."""
        comment_parts = [f"Imported on {datetime.now().strftime('%Y-%m-%d')}"]

        if filament_data.get('extruder_temp') and filament_data.get('bed_temp'):
            comment_parts.append(f"Temps: {filament_data['extruder_temp']}°C/{filament_data['bed_temp']}°C")

        if filament_data.get('vendor_description'):
            comment_parts.append(filament_data['vendor_description'])
        
        if import_id:
            comment_parts.append(f"ImportID: [{import_id}]")

        return " | ".join(comment_parts)

    def get_material_density(self, material: str) -> float:
        """Get material density from vendor data or fallback"""
        material_defaults = self.vendor_data.get("material_defaults", {})
        base_material = self.extract_base_material(material.upper())

        if base_material in material_defaults:
            return material_defaults[base_material].get('density', 1.24)

        # Fallback densities if not in vendor data
        fallback_densities = {
            'PLA': 1.24,
            'ABS': 1.04,
            'PETG': 1.27,
            'TPU': 1.20,
            'WOOD': 1.28,
            'SILK': 1.24,
            'ASA': 1.07
        }
        return fallback_densities.get(base_material, 1.24)

    def load_filaments_from_json(self, json_path: str) -> List[Dict]:
        """Load filament data from JSON file"""
        try:
            with open(json_path, 'r', encoding='utf-8') as file:
                data = json.load(file)

            # Handle both direct array and wrapped object formats
            if isinstance(data, list):
                filaments = data
            elif isinstance(data, dict) and 'filaments' in data:
                filaments = data['filaments']
            else:
                print("JSON should contain a 'filaments' array or be an array directly")
                return []

            # Validate filament data
            validated_filaments = []
            for i, filament in enumerate(filaments):
                if not isinstance(filament, dict):
                    print(f"Warning: Skipping invalid filament at index {i}")
                    continue

                # Set defaults for missing fields
                validated_filament = {
                    'brand': filament.get('brand', 'Unknown'),
                    'material': filament.get('material', 'PLA'),
                    'color': filament.get('color', 'Unknown'),
                    'diameter': float(filament.get('diameter', 1.75)),
                    'weight': float(filament.get('weight', 1000)),
                    'price': float(filament.get('price', 0.0)),
                    'quantity': int(filament.get('quantity', 1)),
                    'spool_weight': float(filament['spool_weight']) if filament.get('spool_weight') else None
                }
                validated_filaments.append(validated_filament)

            return validated_filaments

        except FileNotFoundError:
            print(f"JSON file not found: {json_path}")
            return []
        except json.JSONDecodeError as e:
            print(f"Invalid JSON format: {e}")
            return []
        except Exception as e:
            print(f"Error loading JSON: {e}")
            return []

    def process_receipt(self, pdf_path: str = None, json_path: str = None, vendor_name: str = None,
                        dry_run: bool = False) -> bool:
        """Process a receipt PDF or JSON file and import filaments"""
        source_filename = pdf_path or json_path
        
        # Get all existing filaments from Spoolman to avoid creating duplicates
        existing_filaments = self.get_filaments()
        if not dry_run:
            print(f"Found {len(existing_filaments)} existing filaments in Spoolman.")

        if json_path:
            print(f"Processing JSON file: {json_path}")
            filaments = self.load_filaments_from_json(json_path)
        elif pdf_path:
            print(f"Processing receipt: {pdf_path}")
            receipt_text = self.extract_text_from_pdf(pdf_path)
            if not receipt_text:
                return False
            filaments = self.extract_filaments_with_llm(receipt_text) or self.extract_filaments_pattern_matching(receipt_text)
        else:
            print("Error: Either PDF path or JSON path must be provided")
            return False

        if not filaments:
            print("No filaments found")
            return False

        print(f"Found {len(filaments)} filament(s) to process:")
        for i, filament in enumerate(filaments, 1):
            print(f"  {i}. {filament['brand']} {filament['material']} {filament['color']}")

        if dry_run:
            print("\n--- DRY RUN ---")
            # ... (dry run logic remains the same)
            return True

        # --- Interactive Import ---
        success_count = 0
        for filament in filaments:
            vendor_to_use = filament['brand'] or vendor_name
            if not vendor_to_use:
                vendor_to_use = input(f"Enter vendor for {filament['material']} {filament['color']}: ")
            
            vendor_data = self.get_vendor_filament_data(vendor_to_use, filament['material'], interactive=True)
            if vendor_data is None:
                print(f"Skipping filament: {filament['brand']} {filament['material']}")
                continue

            filament.update(vendor_data)
            if filament.get('spool_weight') is None:
                filament['spool_weight'] = vendor_data.get('spool_weight')

            vendor_id = self.get_or_create_vendor(vendor_to_use)
            if not vendor_id:
                print(f"Failed to get or create vendor '{vendor_to_use}'. Skipping filament.")
                continue

            if self.import_filament(filament, vendor_id, existing_filaments, source_filename, interactive=not dry_run):
                success_count += 1

        print(f"\nSuccessfully imported {success_count}/{len(filaments)} filaments")
        return success_count > 0


import os
from dotenv import load_dotenv

# ... (rest of the imports)

# ... (class definition)

def main():
    load_dotenv()  # Load environment variables from .env file

    parser = argparse.ArgumentParser(description='Import filaments from PDF receipts or JSON files to Spoolman')

    # Create mutually exclusive group for input source
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument('--pdf', help='Path to PDF receipt file')
    input_group.add_argument('--json', help='Path to JSON file containing filament data')

    parser.add_argument('--spoolman-url', 
                        default=os.getenv('SPOOLMAN_URL', 'http://localhost:7912'),
                        help='Spoolman URL. Defaults to SPOOLMAN_URL env var or http://localhost:7912')
    parser.add_argument('--vendor', help='Fallback vendor name if not specified in the input file')
    parser.add_argument('--openai-key', 
                        default=os.getenv('OPENAI_API_KEY'),
                        help='OpenAI API key. Defaults to OPENAI_API_KEY env var.')
    parser.add_argument('--dry-run', action='store_true', help='Extract data but do not import')

    args = parser.parse_args()
    
    # ... (rest of the function)


    # Check file existence
    if args.pdf and not Path(args.pdf).exists():
        print(f"Error: PDF file not found: {args.pdf}")
        sys.exit(1)
    elif args.json and not Path(args.json).exists():
        print(f"Error: JSON file not found: {args.json}")
        sys.exit(1)

    importer = SpoolmanImporter(args.spoolman_url, args.openai_key)

    try:
        success = importer.process_receipt(
            pdf_path=args.pdf,
            json_path=args.json,
            vendor_name=args.vendor,
            dry_run=args.dry_run
        )
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()