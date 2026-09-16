import os
import chromadb

def purge():
    root = os.path.dirname(os.path.abspath(__file__))
    chroma_dir = os.path.join(root, "data", "chroma")
    
    try:
        client = chromadb.PersistentClient(path=chroma_dir)
        try:
            client.delete_collection("generated_tools")
            print("Deleted generated_tools collection")
        except Exception as e:
            print("Could not delete generated_tools:", e)
            
        try:
            client.delete_collection("project_tools")
            print("Deleted project_tools collection")
        except Exception as e:
            print("Could not delete project_tools:", e)
            
        try:
            # Also reset builtin_tools just in case there are duplicates
            client.delete_collection("builtin_tools")
            print("Deleted builtin_tools collection")
        except Exception as e:
            print("Could not delete builtin_tools:", e)
            
    except Exception as e:
        print("Failed to connect to ChromaDB:", e)

if __name__ == "__main__":
    purge()
