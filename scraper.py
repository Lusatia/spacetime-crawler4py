import re
import atexit
import json
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from collections import Counter
from urllib.parse import urlparse, urldefrag, urljoin
from hashlib import md5

scrapes = 0
urls = set()
checksums = set()
longest_page = {"url":"","word_count":-1}
word_freq = Counter()
subdomain_freq = Counter()

# Stopwords modified to fit the tokenizer
STOPWORDS = {"a","about","above","after","again","against","all","am","an","and","any","are","aren","as","at","be","because","been","before","being","below","between","both","but","by","can","cannot","could","couldn","did","didn","t","do","does","doesn","doing","don","down","during","each","few","for","from","further","had","hadn","has","hasn","have","having","he","d","ll","s","her","here","hers","herself","him","himself","his","how","i","ve","if","in","into","is","isn","it","its","itself","let","me","more","most","mustn","my","myself","no","nor","not","of","off","on","once","only","or","other","ought","our","ours","ourselves","out","over","own","same","she","should","shouldn","so","some","such","than","that","the","their","theirs","them","themselves","then","there","they","re","this","those","through","to","too","under","until","up","very","was","wasn","we","were","weren","what","when","which","while","who","whom","why","with","would","wouldn","you","your","yours","yourself","yourselves"}

def save_analytics():
	data = {
		"unique_pages": len(urls),
		"longest_page_url": longest_page,
		"top50_words": word_freq.most_common(50),
		"subdomains": dict(sorted(subdomain_freq.items()))
	}
	print(data)
	with open("stats.json","w") as f:
		json.dump(data, f, indent = 4)

atexit.register(save_analytics)

def scraper(url, resp):
	global scrapes
	
	if resp is None or resp.raw_response is None:
		print("Empty response")
		return []

	if not resp.raw_response.headers.get("Content-Type", '').lower().startswith("text/html"):
		print("Non-webpage")
		return []

	if not (200 <= resp.status < 300):
		print(f"Status code {resp.status}")
		return []
	
	content_size = len(resp.raw_response.content)
	if content_size > 1000000:
		print(f"Content exceeds 1 MB at {content_size} bytes")
		return []

	soup = BeautifulSoup(resp.raw_response.content, "html.parser")
	text = soup.get_text()
	
	checksum = md5(text.encode()).hexdigest()
	if checksum in checksums:
		print("Hash collision, likely duplicate")
		return []

	checksums.add(checksum)

	tokens = [t for t in re.findall(r"[a-z]+", text.lower()) if t not in STOPWORDS]
	length = len(tokens)

	if length == 0 or len(set(tokens)) / len(tokens) < 0.1:
		print("Low information page")
		return []

	if length > longest_page['word_count']:
		longest_page['url'] = url
		longest_page['word_count'] = length

	word_freq.update(tokens)

	links = extract_next_links(url, resp)
	urls.update(links)
	for link in links:
		if link in urls:
			continue
		parsed = urlparse(url)
		if parsed.hostname.lower().endswith("uci.edu"):
			subdomain_freq[parsed.hostname] += 1

	scrapes += 1
	if scrapes % 50 == 0:
		save_analytics()

	return [link for link in links if is_valid(link)]

def extract_next_links(url, resp):
	# Implementation required.
	# url: the URL that was used to get the page
	# resp.url: the actual url of the page
	# resp.status: the status code returned by the server. 200 is OK, you got the page. Other numbers mean that there was some kind of problem.
	# resp.error: when status is not 200, you can check the error here, if needed.
	# resp.raw_response: this is where the page actually is. More specifically, the raw_response has two parts:
	#		 resp.raw_response.url: the url, again
	#		 resp.raw_response.content: the content of the page!
	# Return a list with the hyperlinks (as strings) scrapped from resp.raw_response.content
	if resp.status != 200:
		return []
	
	soup = BeautifulSoup(resp.raw_response.content, "html.parser")

	links = set()

	# No validation will be done except for defragging, it will be up to is_valid to filter the URLs
	for tag in soup.find_all('a', href = True):
		try:
			link = tag["href"]
			if link == '#':
				continue

			defragged_url, _ = urldefrag(urljoin(url, link))
			
			links.add(defragged_url)
		except:
			# Headache reducer
			pass

	return list(links)

def is_valid(url):
	# Decide whether to crawl this url or not. 
	# If you decide to crawl it, return True; otherwise return False.
	# There are already some conditions that return False.
	try:
		parsed = urlparse(url)
		if parsed.scheme not in {"http", "https"}:
			return False
		if re.match(
			r".*\.(css|js|bmp|gif|jpe?g|ico"
			+ r"|png|tiff?|mid|mp2|mp3|mp4"
			+ r"|wav|avi|mov|mpeg|ram|m4v|mkv|ogg|ogv|pdf"
			+ r"|ps|eps|tex|ppt|pptx|doc|docx|xls|xlsx|names"
			+ r"|data|dat|exe|bz2|tar|msi|bin|7z|psd|dmg|iso"
			+ r"|epub|dll|cnf|tgz|sha1"
			+ r"|thmx|mso|arff|rtf|jar|csv"
			+ r"|rm|smil|wmv|swf|wma|zip|rar|gz)$", parsed.path.lower()):
			return False

		# Pull the plug if the url is too long or has too many subdirectories
		if len(url) > 200 or url.count('/') > 20:
			return False

		# Validate URL is within allowed domain
		domains = {".ics.uci.edu",
				   ".cs.uci.edu",
				   ".informatics.uci.edu",
				   ".stat.uci.edu"}
		hostname = parsed.hostname.lower()
		
		# Internal support wiki, not even accessible from the outside web, not worth crawling
		if "swiki" in hostname:
			return False
		if hostname is None or not any(hostname.endswith(d) for d in domains):
			return False

		# Avoiding crawler traps with calendars and shares and searches
		bad_queries = {"tribe-bar-date","ical","outlook-ical","eventdisplay","calendar","date=","sort=","session","replytocom","share="}
		query = parsed.query.lower()
		if any(bq in query for bq in bad_queries):
			return False
		path = parsed.path.lower()
		if re.search(r"/(\d{4})/(\d{2})/(\d{2})", path):
			return False
		if re.search(r"(\d{4})-(\d{2})-(\d{2})", path):
			return False
		if re.search(r"/(\d{4})/(\d{2})/(\d{2})", query):
			return False
		if re.search(r"(\d{4})-(\d{2})-(\d{2})", query):
			return False
		if "calendar" in path:
			return False
		if "/people" in path:
			return False
		if "/happening" in path:
			return False

		return True

	except TypeError:
		print ("TypeError for ", parsed)
		# Peace of mind
		return False
