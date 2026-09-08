# Databricks notebook source
# MAGIC %md
# MAGIC # Customer Insights
# MAGIC
# MAGIC Analyze customer purchase patterns from `samples.tpch`

# COMMAND ----------

# Import libraries
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, sum, count, avg

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load Data

# COMMAND ----------

# Read customer orders
df_orders = spark.table("samples.tpch.orders")
df_customer = spark.table("samples.tpch.customer")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Analysis

# COMMAND ----------

# Join and aggregate
# NOTE: Use explicit join condition when column names differ between tables
customer_insights = (
    df_orders
    .join(df_customer, df_orders.o_custkey == df_customer.c_custkey)
    .groupBy("c_custkey", "c_name", "c_mktsegment")
    .agg(
        count("o_orderkey").alias("total_orders"),
        sum("o_totalprice").alias("total_spent"),
        avg("o_totalprice").alias("avg_order_value")
    )
    .orderBy(col("total_spent").desc())
)

# Display results
display(customer_insights.limit(20))
