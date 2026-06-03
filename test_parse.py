import re
from bs4 import BeautifulSoup

def find_deepest_match(soup, pattern):
    def is_match(tag):
        if not tag.name: return False
        if not pattern.search(tag.get_text(" ", strip=True)): return False
        for child in tag.find_all(recursive=True):
            if child.name and pattern.search(child.get_text(" ", strip=True)):
                return False
        return True
        
    label_elem = soup.find(is_match)
    if not label_elem: return None
    
    while label_elem.name in ["b", "strong", "i", "em", "u", "span"] and label_elem.parent:
        label_elem = label_elem.parent
    return label_elem

htmls = [
    "<div><h2>Fund Overview</h2><p>This is a good fund.</p></div>",
    "<tr><td><b>Expense Ratio</b></td><td>0.8%</td></tr>",
    "<div><div>Expense Ratio</div><div>Regular: 1.2% Direct: 0.5%</div></div>"
]
patterns = [
    re.compile(r"Overview", re.IGNORECASE),
    re.compile(r"Expense Ratio", re.IGNORECASE),
    re.compile(r"Expense Ratio", re.IGNORECASE)
]

for html, pattern in zip(htmls, patterns):
    soup = BeautifulSoup(html, "lxml")
    label_elem = find_deepest_match(soup, pattern)
    print("HTML:", html)
    print("Label Elem:", label_elem)

