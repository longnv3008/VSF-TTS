import json

data = json.load(open("labeled.json"))

with open("text2", "w") as f:
    for record in data:
        text = record["transcription"]
        text = text if type(text) == str else text["text"][0]
        f.write("{} {}\n".format(record["audio"], text))

