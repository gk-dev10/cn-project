import unittest

from application.location_service import LocationService


class LocationServiceTests(unittest.TestCase):
    def test_set_location_returns_payload(self):
        service = LocationService()

        location = service.set_location(12.9716, 77.5946, label="Bengaluru")

        self.assertEqual(location.latitude, 12.9716)
        self.assertEqual(location.longitude, 77.5946)
        self.assertEqual(service.current_payload()["label"], "Bengaluru")

    def test_invalid_coordinates_rejected(self):
        service = LocationService()

        with self.assertRaises(ValueError):
            service.set_location(91, 0)
        with self.assertRaises(ValueError):
            service.set_location(0, 181)


if __name__ == "__main__":
    unittest.main()

