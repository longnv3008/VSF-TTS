import json
import sys

prefix=sys.argv[3]

with open(sys.argv[1]) as fin, open(sys.argv[2], "w") as fout:
    data = []
    for line in fin:
        cols = line.strip().split("\t")
        if len(cols) != 2:
            #print(line)
            #continue
            path = cols[0]
            text = ""
        else:
            path, text = cols
        text = " ".join(text.strip().split())
        if text or True:
            name = path.split("/")[-1]
            url = f"/data/local-files?d={prefix}/{name}"
            data.append({
                    "audio": url,
                    "text": text
            })
    json.dump(data, fout, indent=4, ensure_ascii=False)
