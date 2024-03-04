import re
from typing import Callable, Optional, List
from urllib.parse import urlparse

import requests
import tiktoken
import apache_beam as beam
from apache_beam.options.pipeline_options import PipelineOptions
from apache_beam.transforms.sql import SqlTransform
from bs4 import BeautifulSoup
from langchain import LLMChain, GoogleSearchAPIWrapper
from langchain.base_language import BaseLanguageModel
from tiktoken import Encoding

from apache_beam_ai.prompt import (
  SEARCH_PROMPT,
  SQL_PROMPT,
  TRANSFORM_PROMPT
)


class AITransform:
  _HTTP_HEADER = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                  " (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
  }

  def __init__(
      self,
      llm: BaseLanguageModel,
      web_search_tool: Optional[Callable[[str], str]] = None,
      beam_pipeline: Optional[beam.Pipeline] = None,
      beam_options: Optional[PipelineOptions] = None,
      encoding: Optional[Encoding] = None,
      max_tokens_of_web_content: int = 3000,
      verbose: bool = False,
  ) -> None:
    """
    Initialize the AITransform object with the provided parameters.
    :param llm: LLM instance for selecting web search result
                             and writing the ingestion SQL query.
    :param web_search_tool: optional function to perform web search,
                            Google search will be used if not provided
    :param beam_pipeline: optional Beam Pipeline, a new one will be created
                          if not provided
    :param beam_options: optional Beam PipelineOptions, to override
                         default Beam Pipeline's PipelineOptions override
    :param encoding: optional Encoding, cl100k_base will be used if not provided
    :param max_tokens_of_web_content: maximum tokens of web content after encoding
    """
    self._pipeline = beam_pipeline or beam.Pipeline(options=beam_options)
    self._llm = llm
    self._web_search_tool = web_search_tool or self._default_web_search_tool
    self._encoding = encoding or tiktoken.get_encoding("cl100k_base")
    self._max_tokens_of_web_content = max_tokens_of_web_content
    self._search_llm_chain = LLMChain(llm=self._llm, prompt=SEARCH_PROMPT)
    self._sql_llm_chain = LLMChain(llm=self._llm, prompt=SQL_PROMPT)
    self._transform_chain = LLMChain(llm=llm, prompt=TRANSFORM_PROMPT)
    self._verbose = verbose

  @staticmethod
  def _extract_table_name(query: str) -> str:
    """
    Extract the table name from the provided SQL query.
    :param query: SQL query as a string
    :return: table name as a string
    """
    pattern = r"^CREATE EXTERNAL TABLE IF NOT EXISTS (\S+)"
    match = re.search(pattern, query, re.IGNORECASE)
    if not match:
      raise ValueError(
          f"The provided query: '{query}' is not valid for creating a table. "
          "Expected pattern: '^CREATE EXTERNAL TABLE IF NOT EXISTS [TABLE_NAME] ...'"
      )
    return match.group(1)

  @staticmethod
  def _generate_search_prompt(columns: Optional[List[str]]) -> str:
    return (
      f"The best search results should contain as many as possible of these info: {','.join(columns)}"
      if columns is not None and len(columns) > 0
      else ""
    )

  @staticmethod
  def _generate_sql_prompt(columns: Optional[List[str]]) -> str:
    return (
      f"The result view MUST contain following columns: {columns}"
      if columns is not None and len(columns) > 0
      else ""
    )

  @staticmethod
  def _default_web_search_tool(desc: str) -> str:
    search_wrapper = GoogleSearchAPIWrapper()
    return str(search_wrapper.results(query=desc, num_results=10))

  @staticmethod
  def _is_http_or_https_url(s: str):
    result = urlparse(s)  # Parse the URL
    # Check if the scheme is 'http' or 'https'
    return result.scheme in ["http", "https"]

  def log(self, message: str) -> None:
    if self._verbose:
      print(message)

  def _trim_text_from_end(self, text: str, max_tokens: int) -> str:
    """
    Trim text from the end based on the maximum number of tokens allowed.
    :param text: text to trim
    :param max_tokens: maximum tokens allowed
    :return: trimmed text
    """
    tokens = list(self._encoding.encode(text))
    if len(tokens) > max_tokens:
      tokens = tokens[:max_tokens]
    return self._encoding.decode(tokens)

  def _get_url_from_search_tool(self, desc: str, columns: Optional[List[str]]) -> str:
    search_result = self._web_search_tool(desc)
    search_columns_hint = self._generate_search_prompt(columns)
    # Run the LLM chain to pick the best search result
    return self._search_llm_chain.run(
        query=desc, search_results=search_result, columns={search_columns_hint}
    )

  def _create_dataframe_with_llm(
      self, text: str, desc: str, columns: Optional[List[str]]
  ) -> DataFrame:
    clean_text = " ".join(text.split())
    web_content = self._trim_text_from_end(
        clean_text, self._max_tokens_of_web_content
    )

    sql_columns_hint = self._generate_sql_prompt(columns)

    # Run the LLM chain to get an ingestion SQL query
    sql_query = self._sql_llm_chain.run(
        query=desc, web_content=web_content, columns=sql_columns_hint
    )
    self.log(f"SQL query for the ingestion:\n {sql_query}\n")

    table_name = self._extract_table_name(sql_query)
    self.log(f"Storing data into temp table: {table_name}\n")
    self._pipeline.apply(SqlTransform.)
    return self._spark.table(table_name)

  def create_df(self, desc: str, columns: Optional[List[str]] = None) -> DataFrame:
    """
    Create a Spark DataFrame by querying an LLM from web search result.
    :param desc: the description of the result DataFrame, which will be used for
                 web searching
    :param columns: the expected column names in the result DataFrame
    :return: a Spark DataFrame
    """
    url = desc.strip()  # Remove leading and trailing whitespace
    is_url = self._is_http_or_https_url(url)
    # If the input is not a valid URL, use search tool to get the dataset.
    if not is_url:
      url = self._get_url_from_search_tool(desc, columns)

    self.log(f"Parsing URL: {url}\n")
    try:
      response = requests.get(url, headers=self._HTTP_HEADER)
      response.raise_for_status()
    except requests.exceptions.HTTPError as http_err:
      self.log(f"HTTP error occurred: {http_err}")
      return
    except Exception as err:
      self.log(f"Other error occurred: {err}")
      return

    soup = BeautifulSoup(response.text, "html.parser")
    # If the input is a URL link, use the title of web page as the dataset's description.
    if is_url:
      desc = soup.title.string
    return self._create_dataframe_with_llm(soup.get_text(), desc, columns)

  def transform_df(self, df: DataFrame, desc: str) -> DataFrame:
    """
    This method applies a transformation to a provided Spark DataFrame, the specifics of which are determined by the 'desc' parameter.
    :param df: The Spark DataFrame that is to be transformed.
    :param desc: A natural language string that outlines the specific transformation to be applied on the DataFrame.
    :return: Returns a new Spark DataFrame that is the result of applying the specified transformation on the input DataFrame.
    """
    temp_view_name = "temp_view_for_transform"
    df.createOrReplaceTempView(temp_view_name)
    schema_str = "\n".join([f"{name}: {dtype}" for name, dtype in df.dtypes])
    sql_query = self._transform_chain.run(
        view_name=temp_view_name, columns=schema_str, desc=desc
    )
    self.log(f"SQL query for the transform:\n{sql_query}")
    return self._spark.sql(sql_query)