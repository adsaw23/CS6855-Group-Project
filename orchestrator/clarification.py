"""Ask for a metric when proximity or importance is ambiguous."""

import re


def clarification_reason(question):
    text = question.casefold()
    explicit_metric = re.search(
        r"\b(hops?|flights?|steps?|distance|kilomet(?:er|re)s?|miles?|weighted|unweighted|"
        r"closeness|jaccard|similarity|pagerank|page rank|betweenness|degree|"
        r"shared (?:chapters|neighbou?rs)|common neighbou?rs|edge weight|"
        r"fewest|shortest path|number of links)\b",
        text,
    )
    if not explicit_metric and re.search(r"\bhow\s+(?:close|near)\b", text):
        return (
            "Which measure of closeness do you mean: the number of hops, "
            "weighted distance or interaction strength, or similarity of connections?"
        )
    if not explicit_metric and re.search(r"\bmost\s+(?:important|central)\b", text):
        return (
            "Which importance measure should I use: degree, PageRank, "
            "betweenness, closeness, or another specified metric?"
        )
    return None
