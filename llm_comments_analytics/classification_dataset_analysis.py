import pandas as pd

df = pd.read_csv(r"data/classification_dataset.csv")
# Строка 8 -> relevant
df.iloc[8, df.columns.get_loc("true_relevance")] = "relevant"

# Строка 11 -> relevant
df.iloc[11, df.columns.get_loc("true_relevance")] = "relevant"

# Строка 17 -> relevant
df.iloc[17, df.columns.get_loc("true_relevance")] = "relevant"

# Строка 53 -> irrelevant
df.iloc[
    53,
    [
        df.columns.get_loc("true_message_type"),
        df.columns.get_loc("true_category"),
        df.columns.get_loc("true_subcategory"),
        df.columns.get_loc("true_case"),
    ],
] = [None, None, None, None]

df.to_csv("classification_dataset_fixed.csv", index=False, encoding="utf-8-sig")