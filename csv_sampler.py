import os
import csv

def extract_csv_samples(input_dir, output_dir="samples", lines=10):
    # Create output folder
    os.makedirs(output_dir, exist_ok=True)

    # Loop through all files in the directory
    for filename in os.listdir(input_dir):
        if filename.lower().endswith(".csv"):
            input_path = os.path.join(input_dir, filename)

            # Build output file name: <name>_sample.csv
            name, ext = os.path.splitext(filename)
            output_filename = f"{name}_sample.csv"
            output_path = os.path.join(output_dir, output_filename)

            print(f"Processing: {filename}")

            # Read first N rows
            with open(input_path, "r", encoding="utf-8", newline="") as infile:
                reader = csv.reader(infile)
                sample_rows = [row for _, row in zip(range(lines), reader)]

            # Save sample
            with open(output_path, "w", encoding="utf-8", newline="") as outfile:
                writer = csv.writer(outfile)
                writer.writerows(sample_rows)

            print(f" → Saved sample as: {output_path}\n")


if __name__ == "__main__":
    folder_path = r"./downloads"   # ← change this
    extract_csv_samples(folder_path)
