import subprocess

# Function to run the basic calculator with specific inputs
def run_calculator():
    # Arguments to give to the calculator
    inputs = '1\n5\n3\n'  # Simulate: Add (1), 5, 3
    
    # Running the calculator script
    process = subprocess.Popen(['python', 'basic_calculator.py'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate(input=inputs.encode())

    # Print result
    print(stdout.decode())
    if stderr:
        print('Error:', stderr.decode())

# Execute the function
if __name__ == '__main__':
    run_calculator()