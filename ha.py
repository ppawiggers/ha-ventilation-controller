import requests


class HomeAssistantAPI:
    def __init__(self, ha_url: str, ha_token: str):
        self.ha_url = ha_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {ha_token}",
            "Content-Type": "application/json",
        }
        self.timeout = 10

    def get_state(self, entity_id: str):
        try:
            url = f"{self.ha_url}/api/states/{entity_id}"
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()

            state = response.json()

            # Handle 'unavailable' or 'unknown' states
            if state["state"] in ["unavailable", "unknown", "none", None]:
                return None

            try:
                return float(state["state"])
            except (ValueError, TypeError):
                return state["state"]
        except (requests.RequestException, ValueError, KeyError) as e:
            print(f"Error getting state for {entity_id}: {e}")
            return None

    def call_service(self, domain: str, service: str, **kwargs) -> bool:
        try:
            url = f"{self.ha_url}/api/services/{domain}/{service}"
            response = requests.post(
                url, headers=self.headers, json=kwargs, timeout=self.timeout
            )
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            print(f"Error calling {domain}.{service}: {e}")
            return False

    def set_state(self, entity_id: str, state: str, attributes: dict = None) -> bool:
        try:
            url = f"{self.ha_url}/api/states/{entity_id}"
            data = {"state": state, "attributes": attributes or {}}
            response = requests.post(
                url, headers=self.headers, json=data, timeout=self.timeout
            )
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            print(f"Error setting state for {entity_id}: {e}")
            return False

    def get_attribute(self, entity_id: str, attribute: str):
        """Get a specific attribute value from an entity."""
        try:
            url = f"{self.ha_url}/api/states/{entity_id}"
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()

            state = response.json()

            # Handle missing attributes
            if "attributes" not in state or attribute not in state["attributes"]:
                return None

            return state["attributes"][attribute]
        except (requests.RequestException, ValueError, KeyError) as e:
            print(f"Error getting attribute '{attribute}' for {entity_id}: {e}")
            return None
