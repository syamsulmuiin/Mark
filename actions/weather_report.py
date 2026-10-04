import requests


def weather_action(parameters: dict, player=None, session_memory=None) -> str:
    city = str((parameters or {}).get("city") or "").strip()
    when = str((parameters or {}).get("time") or "today").strip()
    if not city:
        return "Sir, the city is missing for the weather report."
    try:
        r = requests.get(
            f"https://wttr.in/{city}",
            params={"format": "3"},
            headers={"User-Agent": "MARK-LIV/1"},
            timeout=12,
        )
        r.raise_for_status()
        report = r.text.strip()
        if not report:
            raise RuntimeError("weather service returned an empty response")
        result = f"{report} ({when})"
    except Exception as exc:
        result = f"Weather lookup failed: {exc}"
    if session_memory:
        try:
            session_memory.set_last_search(query=f"weather in {city} {when}", response=result)
        except Exception:
            pass
    return result


TOOL = {
    "name": "weather_report",
    "description": "Gets a textual weather report on the headless server without opening a GUI browser.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "city": {"type": "STRING", "description": "City name"},
            "time": {"type": "STRING", "description": "Optional time such as today or tomorrow"},
        },
        "required": ["city"],
    },
    "handler": weather_action,
}
