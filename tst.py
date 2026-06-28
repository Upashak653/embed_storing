# test_sap.py
import requests
import urllib3
urllib3.disable_warnings()

tests = [
    "https://4.188.251.99:8443/sap/opu/odata/sap/",
    "https://4.188.251.99:8443/sap/bc/adt/",
    "https://4.188.251.99:8443/",
]

for url in tests:
    try:
        r = requests.get(url, auth=("rdas","India@15august"),
            headers={"sap-client":"200"}, timeout=5, verify=False)
        print(f"{url} → {r.status_code}")
        if r.status_code == 200:
            print(r.text[:200])
    except Exception as e:
        print(f"{url} → ERROR: {str(e)[:60]}")