import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from plants.models import Crop, Plant, SensorReading

URL = "/api/readings/"
GOOD = {"moisture": 41.5, "light": 12.3, "temp": 23.1, "humidity": 55}


class ReceiveReadingTests(TestCase):
    fixtures = ["crops"]

    def setUp(self):
        owner = get_user_model().objects.create_user("새싹", password="plant-pass-77")
        self.plant = Plant.objects.create(owner=owner, slot="A", crop=Crop.objects.get(slug="tomato"))

    def post(self, body, key=None):
        headers = {"HTTP_X_API_KEY": key} if key is not None else {}
        data = body if isinstance(body, str) else json.dumps(body)
        return self.client.post(URL, data=data, content_type="application/json", **headers)

    def test_url_name(self):
        self.assertEqual(reverse("plants:readings"), URL)

    def test_saves_reading(self):
        res = self.post(GOOD, key=self.plant.api_key)
        self.assertEqual(res.status_code, 201)
        body = res.json()
        self.assertEqual(body["plant"], "A")
        self.assertEqual(body["state"], "ok")
        reading = SensorReading.objects.get()
        self.assertEqual(reading.plant, self.plant)
        self.assertEqual(reading.moisture, 41.5)
        self.assertEqual(reading.humidity, 55.0)

    def test_state_reflects_new_reading(self):
        res = self.post({**GOOD, "moisture": 12}, key=self.plant.api_key)
        self.assertEqual(res.json()["state"], "thirsty")

    def test_missing_key(self):
        self.assertEqual(self.post(GOOD).status_code, 401)
        self.assertFalse(SensorReading.objects.exists())

    def test_wrong_key(self):
        self.assertEqual(self.post(GOOD, key="wrong").status_code, 401)

    def test_invalid_json(self):
        self.assertEqual(self.post("{not json", key=self.plant.api_key).status_code, 400)

    def test_missing_field(self):
        body = dict(GOOD)
        del body["temp"]
        res = self.post(body, key=self.plant.api_key)
        self.assertEqual(res.status_code, 400)
        self.assertIn("temp", res.json()["fields"])

    def test_rejects_strings_and_bools(self):
        res = self.post({**GOOD, "moisture": "40", "light": True}, key=self.plant.api_key)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(set(res.json()["fields"]), {"moisture", "light"})

    def test_out_of_range(self):
        res = self.post({**GOOD, "humidity": 140}, key=self.plant.api_key)
        self.assertEqual(res.status_code, 400)

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(URL).status_code, 405)

    def test_no_csrf_needed(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        res = client.post(URL, data=json.dumps(GOOD), content_type="application/json", HTTP_X_API_KEY=self.plant.api_key)
        self.assertEqual(res.status_code, 201)
