
import unittest
from unittest.mock import patch, MagicMock
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

    @patch('requests.post')
    @patch('requests.get')
    def test_process_receipt_json(self, mock_get, mock_post):
        # Mock API responses
        mock_get.return_value.json.return_value = [{'id': 1, 'name': 'TestVendor'}]
        mock_post.return_value.raise_for_status.return_value = None
        mock_post.return_value.json.return_value = {'id': 1}

        with patch('builtins.open', new_callable=unittest.mock.mock_open, read_data='[{"brand": "TestVendor", "material": "PLA", "color": "Red"}]'):
            success = self.importer.process_receipt(json_path='dummy.json', vendor_name='TestVendor')
            self.assertTrue(success)

if __name__ == '__main__':
    unittest.main()
