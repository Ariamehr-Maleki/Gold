import requests

headers = {
    "Authorization": "Bearer 86084dc7d9ce61b9d477326be87043a3ae7a3586a9e79dd1bfb6e8a52ad218c9",
    "Content-Type": "application/json"
}
data = {
    "zone": "web_unlocker1",
    "url": "https://geo.brdtest.com/welcome.txt?product=unlocker&method=api",
    "format": "raw"
}

response = requests.post(
    "https://api.brightdata.com/request",
    json=data,
    headers=headers
)
print(response.text)