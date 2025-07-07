
import unittest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))
from src.spoolman_importer import SpoolmanImporter

class TestSpoolmanImporter(unittest.TestCase):

    @patch('src.spoolman_importer.SpoolmanImporter.load_vendor_data')
    def setUp(self, mock_load_vendor_data):
        # Mock the vendor data to avoid file I/O in tests
        mock_load_vendor_data.return_value = {
            "vendors": {
                "TestVendor": {
                    "PLA": {
                        "spool_weight": 200,
                        "extruder_temp": 210,
                        "bed_temp": 60,
                        "density": 1.24
                    }
                }
            },
            "material_defaults": {
                "PLA": {
                    "spool_weight": 250,
                    "extruder_temp": 220,
                    "bed_temp": 60,
                    "density": 1.24
                },
                "PETG": {
                    "spool_weight": 250,
                    "extruder_temp": 240,
                    "bed_temp": 80,
                    "density": 1.27
                }
            }
        }
        self.importer = SpoolmanImporter('http://localhost:7912', 'fake_api_key')

    def test_extract_base_material(self):
        self.assertEqual(self.importer.extract_base_material("PLA"), "PLA")
        self.assertEqual(self.importer.extract_base_material("PLA+"), "PLA")
        self.assertEqual(self.importer.extract_base_material("PETG"), "PETG")
        self.assertEqual(self.importer.extract_base_material("ABS"), "ABS")
        self.assertEqual(self.importer.extract_base_material("UNKNOWN"), "PLA")

    @patch('builtins.open', new_callable=unittest.mock.mock_open, read_data='[{"brand": "TestVendor", "material": "PLA", "color": "Red"}]')
    def test_load_filaments_from_json(self, mock_open):
        filaments = self.importer.load_filaments_from_json('dummy.json')
        self.assertEqual(len(filaments), 1)
        self.assertEqual(filaments[0]['brand'], 'TestVendor')
        self.assertEqual(filaments[0]['material'], 'PLA')

    @patch('src.spoolman_importer.PdfReader')
    def test_extract_text_from_pdf(self, mock_pdf_reader):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Sample PDF text"
        mock_pdf_reader.return_value.pages = [mock_page]
        
        with patch('builtins.open', new_callable=unittest.mock.mock_open):
            text = self.importer.extract_text_from_pdf('dummy.pdf')
            self.assertEqual(text.strip(), "Sample PDF text")

    def test_get_color_hex(self):
        # Exact match
        self.assertEqual(self.importer.get_color_hex("Red", interactive=False), "#FF0000")
        # Case-insensitive match
        self.assertEqual(self.importer.get_color_hex("bLaCk", interactive=False), "#000000")
        # Nuanced match
        self.assertEqual(self.importer.get_color_hex("Light Blue", interactive=False), "#ADD8E6")
        # Partial match
        self.assertEqual(self.importer.get_color_hex("Galaxy Black", interactive=False), "#2E2E2E")
        # Fallback to base color
        self.assertEqual(self.importer.get_color_hex("Deep Blue", interactive=False), "#0000FF")
        # No match
        self.assertIsNone(self.importer.get_color_hex("Chartreuse", interactive=False))

    @patch('src.spoolman_importer.SpoolmanImporter.get_or_create_vendor', return_value=1)
    @patch('requests.post')
    @patch('requests.get')
    def test_reimport_skips_duplicate_spools(self, mock_get, mock_post, mock_get_or_create_vendor):
        # Mock API responses
        mock_get.side_effect = [
            # 1. Get existing filaments
            MagicMock(json=lambda: [{'id': 101, 'name': 'PLA Red', 'vendor': {'id': 1, 'name': 'TestVendor'}}]),
            # 2. Get existing spools for the filament
            MagicMock(json=lambda: [{'id': 201, 'comment': 'ImportID: [imported_from:dummy.json|item:TestVendor-PLA-Red-0.0|index:0]'}])
        ]
        
        with patch('builtins.open', new_callable=unittest.mock.mock_open, read_data='[{"brand": "TestVendor", "material": "PLA", "color": "Red", "quantity": 1, "weight": 1000, "diameter": 1.75, "price": 0.0}]'):
            success = self.importer.process_receipt(json_path='dummy.json')
            self.assertTrue(success)

            # Verify that no new spools were created
            mock_post.assert_not_called()

if __name__ == '__main__':
    unittest.main()
