#!/usr/bin/env python3

"""Lookup an inflection and render html."""

import webbrowser

from jinja2 import Environment, FileSystemLoader
from rich import print
from typing import List

from db.get_db_session import get_db_session
from db.models import PaliWord
from db.models import InflectionToHeadwords

from tools.configger import config_test
from tools.exporter_functions import get_family_compounds
from tools.exporter_functions import get_family_set
from tools.paths import ProjectPaths
from tools.meaning_construction import summarize_construction
from tools.meaning_construction import make_meaning_html
from tools.meaning_construction import make_grammar_line
from tools.meaning_construction import degree_of_completion
from tools.date_and_time import year_month_day
from tools.tic_toc import tic, toc

the_word = "assa"

class HeadwordData():
    def __init__(self, css, js, i, fc, fs):
        self.css = css
        self.js = js
        self.meaning = make_meaning_html(i)
        self.summary = summarize_construction(i)
        self.complete = degree_of_completion(i)
        self.grammar = make_grammar_line(i)
        self.i = self.convert_newlines(i)
        self.fc = fc
        self.fs = fs
        self.app_name = "Jinja"
        self.date = year_month_day()
        if config_test("dictionary", "make_link", "yes"):
            self.make_link = True
        else:
            self.make_link = False
        

    @staticmethod
    def convert_newlines(obj):
        for attr_name in dir(obj):
            if not attr_name.startswith('_'):  # skip private and protected attributes
                attr_value = getattr(obj, attr_name)
                if isinstance(attr_value, str):
                    try:
                        setattr(obj, attr_name, attr_value.replace("\n", "<br>"))
                    except AttributeError:
                        continue  # skip attributes that don't have a setter
        return obj

def main(pth, db_session):
    
    headwords: List[str] = lookup_inflection(pth, db_session, the_word)

    if headwords:
        make_html(pth, headwords)
    else:
        open_html_in_browser(pth, "<h3>Nope</h3>")


def lookup_inflection(pth, db_session, the_word):
    inflection = db_session.query(InflectionToHeadwords)\
        .filter_by(inflection=the_word).first()
    if inflection:
        return inflection.headwords_list
    else:
        return []


def make_html(
        pth: ProjectPaths,
        headwords: List[str]
):
    """"Create html from jinja template."""

    tic()

    db_session = get_db_session(pth.dpd_db_path)

    env = Environment(loader=FileSystemLoader(pth.jinja_templates_dir))
    header_templ = env.get_template("header.html")
    word_template = env.get_template("complete_word.html")

    # header
    with open(pth.dpd_css_path) as f:
        css = f.read()
    with open(pth.buttons_js_path) as f:
        js = f.read()

    html = header_templ.render(css=css, js=js)

    # iterate over headwords
    results = db_session.query(PaliWord)\
        .filter(PaliWord.pali_1.in_(headwords)).all()

    for counter, i in enumerate(results):
        fc = get_family_compounds(i)
        fs = get_family_set(i)
        d = HeadwordData(css, js, i, fc, fs)
        html += word_template.render(d=d)
    
    db_session.close()
    open_html_in_browser(pth, html)

    toc()


def open_html_in_browser(pth, html_content):
    path = f"{pth.temp_html_file_path}"
    try:
        with open(path, 'w') as tmp:
            tmp.write(html_content)
        webbrowser.open_new_tab("file://" + path)
    except Exception as e:
        print(f"An error occurred while opening the HTML in the browser: {e}")


if __name__ == "__main__":
    pth = ProjectPaths()
    db_session = get_db_session(pth.dpd_db_path)
    main(pth, db_session)
