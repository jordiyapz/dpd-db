#!/usr/bin/env python3.11

import os
import pickle
import json

import numpy as np
import pandas as pd

from rich import print
from difflib import SequenceMatcher
from css_html_js_minify import css_minify


from dpr_breakup import make_dpr_breakup_dict

from db.get_db_session import get_db_session
from db.models import Sandhi

from tools.stardict import export_words_as_stardict_zip, ifo_from_opts
from tools.timeis import tic, toc
from tools.paths import ProjectPaths as PTH

ADD_DO = True


def main():
    tic()
    print("[bright_yellow]post-processing sandhi-splitter")

    if ADD_DO is True:
        print("[green]add digital ocean [orange]true")
    else:
        print("[green]add digital ocean [orange]false")

    global db_session
    db_session = get_db_session("dpd.db")

    with open(PTH.neg_inflections_set_path, "rb") as f:
        neg_inflections_set = pickle.load(f)

    matches_df = process_matches(PTH, neg_inflections_set)
    top_five_dict = make_top_five_dict(matches_df)
    add_to_dpd_db(top_five_dict)
    transliterate_sandhi()
    make_rule_counts(PTH, matches_df)
    letter_counts(PTH, matches_df)

    dpr_breakup_dict = make_dpr_breakup_dict(PTH)
    make_golden_dict(PTH, top_five_dict, dpr_breakup_dict)
    unzip_and_copy(PTH)
    toc()


def process_matches(PTH, neg_inflections_set):

    print("[green]processing matches")

    print("reading tsvs")
    matches_df = pd.read_csv(PTH.matches_path, dtype=str, sep="\t")

    if ADD_DO is True:
        matches_do_df = pd.read_csv(
            PTH.matches_do_path, dtype=str, sep="\t")
        matches_df = pd.concat([matches_df, matches_do_df], ignore_index=True)

    matches_df = matches_df.fillna("")

    print("adding manual")
    matches_df["manual"] = matches_df['process'].str.count("spelling|variant|manual")

    print("adding splitcount")
    matches_df["splitcount"] = matches_df['split'].str.count(r' \+ ')

    print("adding lettercount")
    matches_df["lettercount"] = matches_df['split'].str.count('.')

    print("adding word count")
    matches_df['count'] = matches_df.groupby('word')['word'].transform('size')

    def calculate_ratio(original, split):
        split = split.replace(" + ", "")
        return SequenceMatcher(None, original, split).ratio()

    print("adding difference ratio")
    matches_df['ratio'] = np.vectorize(
        calculate_ratio)(matches_df['split'], matches_df['split'])

    print("adding neg_count")

    def neg_counter(row):
        neg_count = 0
        if " + " in row["split"]:
            word_list = row["split"].split(" + ")
            # doesn't matter if the first word is negative
            word_list.remove(word_list[0])
            for word in word_list:
                if word in neg_inflections_set:
                    neg_count += 1
        return neg_count

    matches_df['neg_count'] = matches_df.apply(neg_counter, axis=1)

    print("sorting df values")
    matches_df.sort_values(
        by=["manual", "splitcount", "lettercount", "ratio", "neg_count"],
        axis=0,
        ascending=[False, True, True, False, True],
        inplace=True,
        ignore_index=True
    )

    print("dropping duplicates")
    matches_df.drop_duplicates(
        subset=['word', 'split'],
        keep='first',
        inplace=True,
        ignore_index=True
    )

    print("saving to matches_sorted.tsv")
    matches_df.to_csv(PTH.matches_sorted, sep="\t", index=None)

    return matches_df


def make_top_five_dict(matches_df):
    print("[green]making top five dict", end=" ")
    top_five_dict = {}

    for index, i in matches_df.iterrows():

        if i.word not in top_five_dict:
            top_five_dict[i.word] = {
                "splits": [i.split],
                "splitcount": i.splitcount}
        else:
            if len(top_five_dict[i.word]["splits"]) < 5:
                if i.splitcount <= top_five_dict[i.word]["splitcount"]:
                    top_five_dict[i.word]["splits"].append(i.split)

    # print(top_five_dict["ārammaṇamūlakasappāyakārīsuttā"])

    # remove the splitcount
    for key, value in top_five_dict.items():
        top_five_dict[key] = value["splits"]

    print(len(top_five_dict))
    return top_five_dict


def add_to_dpd_db(top_five_dict):
    print("[green]adding to dpd_db", end=" ")

    db_session.execute(Sandhi.__table__.delete())
    db_session.commit()

    add_to_db = []
    for word, splits in top_five_dict.items():
        sandhi_split = Sandhi(
            sandhi=word,
            split=",".join(splits)
        )
        add_to_db.append(sandhi_split)

    db_session.add_all(add_to_db)
    db_session.commit()
    db_session.close()

    print(f"{len(add_to_db)}")


def make_golden_dict(PTH, top_five_dict, dpr_breakup_dict):

    # !!! make goldendict from db using inflections

    print("[green]generating goldendict", end=" ")

    with open(PTH.sandhi_css_path) as f:
        sandhi_css = f.read()
    sandhi_css = css_minify(sandhi_css)

    sandhi_data_list = []
    for word, split_list in top_five_dict.items():
        html_string = sandhi_css
        html_string += "<body><div class='sandhi'><p class='sandhi'>"

        for split in split_list:
            html_string += split

            if split != split_list[-1]:
                html_string += "<br>"
            else:
                html_string += "</p></div>"

        if word in dpr_breakup_dict:
            html_string += dpr_breakup_dict[word]

        html_string += "</body>"

        sandhi_data_list += [{
            "word": word,
            "definition_html": html_string,
            "definition_plain": "",
            "synonyms": ""
        }]

    for word, breakup in dpr_breakup_dict.items():
        if word not in top_five_dict:
            html_string = sandhi_css
            html_string += f"<body>{breakup}</body>"

        sandhi_data_list += [{
            "word": word,
            "definition_html": html_string,
            "definition_plain": "",
            "synonyms": ""
        }]

    zip_path = PTH.sandhi_zip_path

    ifo = ifo_from_opts({
        "bookname": "DPD Splitter",
        "author": "Bodhirasa",
        "description": "DPD Splitter + DPR Analysis",
        "website": "https://digitalpalidictionary.github.io/"
        })

    export_words_as_stardict_zip(sandhi_data_list, ifo, zip_path)

    print("[white]ok")


def unzip_and_copy(PTH):

    print("[green]unipping and copying goldendict", end=" ")

    os.popen(
        f'unzip -o {PTH.sandhi_zip_path} -d "/home/bhikkhu/Documents/Golden Dict"')

    print("[white]ok")


def make_rule_counts(PTH, matches_df):
    print("[green]saving rule counts", end=" ")

    rules_list = matches_df[['rules']].values.tolist()
    rule_counts = {}

    for sublist in rules_list:
        for item in sublist[0].split(','):
            if item not in rule_counts:
                rule_counts[item] = 1
            else:
                rule_counts[item] += 1

    df = pd.DataFrame.from_dict(rule_counts, orient="index", columns=["count"])
    counts_df = df.value_counts()
    counts_df.to_csv(PTH.rule_counts_path, sep="\t")

    print("[white]ok")


def letter_counts(PTH, df):
    print("[green]saving letter counts", end=" ")
    df.drop_duplicates(subset=['word', 'split'],
                       keep='first', inplace=True, ignore_index=True)
    masterlist = []
    for row in range(len(df)):
        split = df.loc[row, "split"]
        if "<i>" not in split:
            words = split.split(" + ")
            for word in words:
                masterlist.append(word)
    masterlist = sorted(masterlist)

    letters = {}
    for i in range(1, 11):
        letters[i] = []

    for word in masterlist:
        if len(word) >= 10:
            letters[10].append(word)
        else:
            letters[len(word)].append(word)

    for i in range(1, 11):
        letters_df = pd.DataFrame(letters[i])
        letters_counts_sorted = letters_df.value_counts()
        letters_path = getattr(PTH, f"letters{i}")
        letters_counts_sorted.to_csv(letters_path, sep="\t", header=None)

    print("[white]ok")


if __name__ == "__main__":
    main()