import psycopg2

def get_database_schema():
    try:
        conn = psycopg2.connect(
            host="localhost",
            port="5432",
            user="postgres",           
            password="@kiL2207",   
            dbname="community_mca" 
        )
        cursor = conn.cursor()

        query = """
        SELECT table_name, column_name, data_type 
        FROM information_schema.columns 
        WHERE table_schema = 'public' 
        ORDER BY table_name, ordinal_position;
        """
        
        cursor.execute(query)
        schema_records = cursor.fetchall()
        
        # Process and format the data for the LLM prompt
        schema_dict = {}
        for table, column, dtype in schema_records:
            if table not in schema_dict:
                schema_dict[table] = []
            schema_dict[table].append(f"{column} ({dtype})")
            
        formatted_schema = ""
        for table, columns in schema_dict.items():
            formatted_schema += f"Table: {table}\nColumns:\n"
            for col in columns:
                formatted_schema += f"  - {col}\n"
            formatted_schema += "\n"
            
        cursor.close()
        conn.close()
        
        return formatted_schema

    except Exception as e:
        return f"Database connection failed: {e}"

if __name__ == "__main__":
    schema_string = get_database_schema()
    print("Extracted Database Schema for LLM Context:\n")
    print(schema_string)