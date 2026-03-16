import requests
from bs4 import BeautifulSoup

url = "https://funpay.com/en/lots/offer?id=65512435"
r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
soup = BeautifulSoup(r.text, "html.parser")

# Print all text-containing divs that might be description
for el in soup.find_all(['div','p'], class_=True):
    text = el.text.strip()
    if len(text) > 30 and len(text) < 2000:
        print(f"class={el.get('class')} | {text[:120]}")
        print("---")