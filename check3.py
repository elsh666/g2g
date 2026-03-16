import requests
from bs4 import BeautifulSoup

r = requests.get('https://funpay.com/en/lots/1400/', headers={'User-Agent': 'Mozilla/5.0'})
soup = BeautifulSoup(r.text, 'html.parser')

europe = [i for i in soup.select('.tc-item') 
          if i.select_one('.tc-server') and 'Europe' in i.select_one('.tc-server').text]

print(f"Europe лотов: {len(europe)}\n")
print("Первые 10 названий:")
for item in europe[:10]:
    title = item.select_one('.tc-desc-text')
    print(repr(title.text.strip()) if title else 'NO TITLE')
