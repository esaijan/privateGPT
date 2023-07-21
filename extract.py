import json
import urllib
import requests
import re

import sqlalchemy

from sqlalchemy import text
from tika import parser
from textacy import preprocessing as textacy_preprocessing


def get_config_file():
    with open("config.json", "r") as f:
        config = json.load(f)
    return config


def connect_to_database(database: str) -> sqlalchemy.engine:
    config = get_config_file()
    try:
        database_engine = sqlalchemy.create_engine(
            sqlalchemy.engine.URL.create(
                drivername="mysql+pymysql",
                username=config[database]["username"],
                password=urllib.parse.quote_plus(config[database]["password"]),
                host=config[database]["host"],
                port=config[database]["port"],
                database=config[database]["db"],
            )
        )
    except Exception as ex:
        print("Error connecting to", database, "Database: ", ex)
    else:
        print("Connected to", database, "Database.")
        return database_engine

def query_extracted_transmittal_data():
    conn = connect_to_database("cobi_dash").connect()
    query = f"""select * from cobidash.extracted_transmittal_data order by extraction_score desc limit 50;"""
    results = conn.execute(text(query))
    conn.close()
    
    return results

def select_letter_body(preprocessed_text):
    letter_pattern = r"(?<=Dear)(.|\n)*(?=Sincerely\,)"
    irrelevant_text_patterns = [
        r"Page\s\d.*\n",  # removes Page # and paper id extracted from pdf
        r"\©.*All rights reserved",  # removes pdf footer -> © 2022 The MITRE Corporation. All rights reserved
        r".*?\d{1,2}\s\w*\s\d{4}",  # removes pdf footer -> author publish-date
        r"\d.*(?=\n{3,})",  # removes footer start w/ numbers
        r"(Mr|Mrs|Ms).*",  # removes authors footer/header
    ]

    letter_body = re.search(letter_pattern, preprocessed_text, re.MULTILINE).group()
    for pattern in irrelevant_text_patterns:
        letter_body = re.sub(pattern, " ", letter_body, 1000, re.MULTILINE)
    return letter_body

def clean_text(letter_body):
    regexes = {
        r"(\n\s\n\n|(?<=\.)\s+\n{2})": "|",  # identifies initial paragraphs from extraction
        r"(\s+\.\|)|(\|\s)": " ",  # removes false identified paragraphs of footers/headers/random newlines
        r"(\|(?=\s*\-))": "",  # removes false identified paragraphs of bullets
        r"\s\.\|\s": "",  # removes dangling false identified paragraphs
        r"\s\n*": " ",  # removes random spaces b/t paragraphs
        r"(\s\.\|)|((?![a-z])\s+\|)": " ",  # removes last leftover/dangling false identified paragraphs
        r"\|": "\\n\\n\\n",  # splits out paragraphs based on | - initial identification
        r"\s*(?=(\-\s|\~|[1-9]\.\s))": " ",  # gets rid of random new lines between sentences
        # r"(?=(If).*((question)|(contact))).*": "",  # gets rid of contact(last) paragraph
        r"(?=\n(In|To|The).*(FAA).*(asked|requested).*MITRE)": "\\n\\n\\n",  # split out tasking summary paragraph
        r"(?=(To).*(accomplish).*MITRE)": "\\n\\n\\n",  # split out accomplishment paragraph
        r"(?=(Impacts|This).*(((work|project).*(allow))|(impact)|(are)).*(FAA|\:))": "\\n\\n\\n",  # split out impact
        # paragraph
        r"(?=(\n|^MITRE|The){1}.*\b(recommends|recommendation|recommended)\b.*FAA)": "\\n\\n\\n",  # split out
        # recommendation paragraph
    }
    for key, value in regexes.items():
        p = re.compile(key)
        letter_body = p.sub(value, letter_body)
    return letter_body

def normalize_hyphenated_words(text, replace_hyphen_with=None):
    text = textacy_preprocessing.normalize.hyphenated_words(text)
    if replace_hyphen_with is not None:
        text = re.sub(r"(?<=\w)-(?=\w)", replace_hyphen_with, text)
    return text


def preprocess_extracted_text(processed_text):
    processed_text = textacy_preprocessing.normalize.whitespace(processed_text)
    processed_text = textacy_preprocessing.normalize.quotation_marks(processed_text)
    processed_text = normalize_hyphenated_words(processed_text)
    return processed_text


def read_and_extract(url):
    extracted_text = (
            parser.from_file(url)["content"]
            .replace("\u2022", "-")
            .replace("", "-")
            .replace("\no ", "~")
    )
    letter_body = select_letter_body(extracted_text)
    letter_body_cleaned = clean_text(letter_body)
    preprocessed_text = preprocess_extracted_text(letter_body_cleaned)
    
    return preprocessed_text

def write_to_text_file(file_name,text):
    with open("source_documents/"+file_name + ".txt", "w") as text_file:
        text_file.write(text)
    
def crawl_box_documents():
    # Track the documents links that fail to be downloaded from Box
    box_error_doc_links = []

    extracted_transmittal_data = query_extracted_transmittal_data()
    if extracted_transmittal_data:
        for record in extracted_transmittal_data:
            doc_link = record[8]
            try:
                res = read_and_extract(doc_link)
                if not res:
                    print(
                        "An error occurred when downloading and extracting the document with link %s"
                        % (doc_link)
                    )
                    box_error_doc_links.append(doc_link)
                else:
                    write_to_text_file(record[0],res)
            except Exception as e:
                print(
                    "An error occurred when downloading the document with link %s"
                    % doc_link
                )
                print(e)
                box_error_doc_links.append(doc_link)
                continue
    else:
        print("ERROR: extracted_transmittal_data list is empty")

    if box_error_doc_links:
        print(
            "The document links that fail to download from Box and/or failed during extraction: %s"
            % (", ".join(box_error_doc_links))
        )

def extract():
    crawl_box_documents()
    pass
    
if __name__ == "__main__":
    extract()