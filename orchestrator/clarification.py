"""Ask for a metric when proximity or importance is ambiguous."""

import re

# Any of these means the question already says how to measure closeness or
# importance, so the planner (not this pre-check) decides what to do with it.
METRIC_HINT = re.compile(
    r"\b(hops?|flights?|steps?|distance|kilomet(?:er|re)s?|km|miles?|weighted|unweighted|"
    r"closeness|jaccard|similar(?:ity)?|pagerank|page rank|betweenness|degree|"
    r"eigenvector|katz|hits?|hubs?|authorit(?:y|ies)|centrality|"
    r"shared (?:chapters|neighbou?rs)|common neighbou?rs|edge weight|"
    r"fewest|shortest path|number of|connections?|connected|links?|edges?|"
    r"routes?|friends?|friendships?|neighbou?rs?|chapters?|"
    r"in terms of|measured|according to|based on|using|by)\b"
)


def clarification_reason(question):
    text = question.casefold()
    if METRIC_HINT.search(text):
        return None
    if re.search(r"\bhow\s+(?:close|near)\b", text):
        return (
            "Which measure of closeness do you mean: the number of hops, "
            "weighted distance or interaction strength, or similarity of connections?"
        )
    if re.search(r"\bmost\s+(?:important|central)\b", text):
        return (
            "Which importance measure should I use: degree, PageRank, "
            "betweenness, closeness, or another specified metric?"
        )
    return None
