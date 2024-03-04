from langchain.prompts.prompt import PromptTemplate

SEARCH_TEMPLATE = """Given a Query and a list of Google Search Results, return the link
from a reputable website which contains the data set to answer the question. {columns}
Query:{query}
Google Search Results: 
```
{search_results}
```
The answer MUST contain the url link only
"""

SEARCH_PROMPT = PromptTemplate(
    input_variables=["query", "search_results", "columns"], template=SEARCH_TEMPLATE
)

SQL_TEMPLATE = """Given the following question:
```
{query}
```
I got the following answer from a web page:
```
{web_content}
```
Give each column a clearly descriptive name (no abbreviations).
If a column can be either String or Numeric, ingest it as Numeric.
Use long type to represent int, prevent overflow.
Currently Beam SQL doesn't handle "decimal" type properly, use "double" to replace it.
Here is an example of how to store data into a test table:
```
 CREATE EXTERNAL TABLE IF NOT EXISTS movies (title VARCHAR, `year` BIGINT) TYPE test;
 INSERT INTO movies VALUES ('Citizen Kane', 1941), ('Schindlers List', 1993);
```
{columns}
The answer MUST contain query only.
"""

SQL_PROMPT = PromptTemplate(
    input_variables=["query", "web_content", "columns"], template=SQL_TEMPLATE
)

TRANSFORM_TEMPLATE = """
Given a Beam test table `{table_name}` with the following columns:
```
{columns}
```
Write a Beam SQL query to retrieve: {desc}
The answer MUST contain query only.
"""

TRANSFORM_PROMPT = PromptTemplate(
    input_variables=["view_name", "columns", "desc"], template=TRANSFORM_TEMPLATE
)