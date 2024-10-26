"""
- This script works on MacOS only.
- It converts Markdown files exported from Joplin into RTFD files that can be easily imported into Apple Notes.
- In Joplin, export your notes using File > Export All > MD - Markdown + Front Matter.
- Then run the script; it should ask for the folder containing the MD files, create the output directory "rtfd_files" and start the conversion process.
- After running this script, go to Apple Notes, choose File > Import to Notes... and select the RTFD folder.
"""

import os
import re
import hashlib
import mimetypes
import requests
import time
from PIL import Image
from datetime import datetime
import markdown
from urllib.parse import unquote
import logging
import shutil

# Setup logging to display information to the user during the process
logging.basicConfig(level=logging.INFO, format='%(message)s')

from Cocoa import (
    NSAttributedString, NSMutableAttributedString, NSData, NSURL, NSDocumentTypeDocumentOption, NSHTMLTextDocumentType,
    NSUTF8StringEncoding, NSBaseURLDocumentOption, NSCharacterEncodingDocumentOption, NSDate, NSFont, NSMakeRange
)
from AppKit import NSFileWrapper, NSTextAttachment
from Foundation import NSFileManager, NSDictionary, NSURL, NSDate, NSFileCreationDate, NSFileModificationDate, NSNotFound

# Logging configuration for detailed error tracking
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Configuration for the conversion process
class ConversionConfig:
    def __init__(self):
        # Maximum allowed filename length
        self.max_filename_length = 100
        # Number of retry attempts for failed downloads
        self.retry_attempts = 3
        # Delay between retry attempts
        self.retry_delay = 2
        # Supported image formats
        self.supported_formats = ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', 'tif', '.webp']
        # Timeout setting for image downloads (in seconds)
        self.download_timeout = 30
        # Maximum allowed download size (in bytes)
        self.max_download_size = 100 * 1024 * 1024  # 100 MB
        # Threshold to identify large attachments (in bytes)
        self.large_attachment_threshold = 10 * 1024 * 1024  # 10 MB
        # CSS for the generated HTML content
        self.custom_css = """
            <style>
            body { font-family: '-apple-system'; font-size: 12pt; }
            h1 { font-size: 24pt; font-weight: bold; }
            h2 { font-size: 18pt; font-weight: bold; }
            h3 { font-size: 16pt; font-weight: bold; }
            h4 { font-size: 14pt; font-weight: bold; }
            h5 { font-size: 12pt; font-weight: bold; }
            h6 { font-size: 12pt; font-weight: bold; }
            p { margin: 0 0 12pt 0; }
            strong, b { font-weight: bold; }
            em, i { font-style: italic; }
            ul, ol { margin: 0 0 12pt 24pt; }
            li { margin: 0 0 6pt 0; }
            blockquote { margin: 0 0 12pt 24pt; font-style: italic; color: #555; }
            code { font-family: Menlo; background-color: #f4f4f4; padding: 2px 4px; }
            pre { font-family: Menlo; background-color: #f4f4f4; padding: 6px; }
            </style>
        """

# Class for tracking issues encountered during the conversion process
class ConversionIssueTracker:
    def __init__(self):
        self.files_with_issues = []  # Files with general issues
        self.files_with_download_issues = []  # Files where image downloads failed
        self.files_with_attachment_issues = []  # Files with problems related to attachments
        self.files_with_invalid_front_matter = []  # Files with invalid front matter
        self.files_with_invalid_attachments = []  # Files with invalid image attachments
        self.rtfd_files_with_attachment_png = []  # Files containing 'Attachment.png' as placeholder
        self.large_attachment_files = []  # Files containing large attachments

    # Add an issue to the appropriate list based on its type
    def add_issue(self, issue_type, message):
        getattr(self, issue_type).append(message)

    # Print a summary of all tracked issues
    def print_summary(self):
        logging.info("\nSummary of Issues:")
        for issue_type in vars(self):
            issues = getattr(self, issue_type)
            if issues:
                logging.info(f"\n{issue_type.replace('_', ' ').title()}:")
                for issue in issues:
                    logging.info(f"- {issue}")

# Main class for converting Joplin notes to RTFD files
class JoplinToRTFDConverter:
    def __init__(self):
        self.config = ConversionConfig()  # Load the configuration settings
        self.issue_tracker = ConversionIssueTracker()  # Instantiate the issue tracker
        self.session = self.initialize_session()  # Initialize a requests session for downloading images

    # Initialize a requests session for network requests with custom headers
    def initialize_session(self):
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'text/html,image/webp,*/*;q=0.8',
        })
        return session

    # Main conversion method that handles the entire process
    def convert(self, input_dir):
        # Setup output and resource directories
        output_dir, resources_dir = self.setup_directories(input_dir)
        if output_dir is None or resources_dir is None:
            return

        # Run the conversion pipeline
        self.run_conversion_pipeline(input_dir, output_dir, resources_dir)

    # Check if a directory contains markdown files
    def has_markdown_files(self, directory):
        for root, _, files in os.walk(directory):
            for file in files:
                if file.endswith('.md') or file.endswith('.html'):
                    return True
        return False

    # Setup output and resource directories for the conversion
    def setup_directories(self, input_dir):
        # Create paths for output and resource directories
        output_dir = os.path.join(os.path.dirname(input_dir), 'rtfd_files')
        resources_dir = os.path.join(input_dir, '_resources')

        # Validate the input directory existence
        if not os.path.isdir(input_dir):
            print(f"\nError: The folder '{input_dir}' does not exist.")
            print("Please create this folder and export your Joplin notes to it before running this script.")
            return None, None

        # Validate if directory contains valid files for conversion
        valid_files = any(
            file.endswith(('.md', '.html'))
            for root, _, files in os.walk(input_dir)
            for file in files
        )

        if not valid_files:
            print(f"\nError: The folder '{input_dir}' has no Markdown or HTML files.")
            print("Please export your notes from Joplin to this folder first.")
            return None, None

        # Manage existing output folder, create if it doesn't exist
        if os.path.exists(output_dir):
            response = input(f"The folder '{output_dir}' already exists. Delete its contents? (y/n): ").strip()
            if response.lower().startswith('y'):
                for filename in os.listdir(output_dir):
                    file_path = os.path.join(output_dir, filename)
                    try:
                        if os.path.isfile(file_path) or os.path.islink(file_path):
                            os.unlink(file_path)  # Remove file or link
                        elif os.path.isdir(file_path):
                            shutil.rmtree(file_path)  # Remove directory
                    except Exception as e:
                        print(f"Error deleting {file_path}: {e}")
                print(f"Deleted all files in '{output_dir}'.")
            else:
                print(f"Keeping files in '{output_dir}'.")
        else:
            os.makedirs(output_dir)  # Create output directory if it does not exist
            print(f"Created the folder '{output_dir}'.")

        return output_dir, resources_dir

    # Clean up output directory if requested by the user
    def clean_output_directory(self, output_dir):
        response = input(
            f"The folder '{output_dir}' already exists. Do you want to delete its contents? (y/n): ").strip().lower()
        if response == 'y':
            for file_name in os.listdir(output_dir):
                file_path = os.path.join(output_dir, file_name)
                if os.path.isfile(file_path):
                    os.remove(file_path)  # Remove file
            logging.info(f"All files in '{output_dir}' have been deleted.")

    # Run the various steps in the conversion pipeline
    def run_conversion_pipeline(self, input_dir, output_dir, resources_dir):
        self.fix_image_extensions(resources_dir, input_dir)  # Fix file extensions for images
        self.download_remote_images(input_dir, resources_dir)  # Download remote images linked in markdown
        self.process_folder_recursively(input_dir, output_dir, resources_dir)  # Convert all files recursively
        self.check_for_large_attachments(output_dir)  # Identify large attachments
        self.check_for_attachment_png(output_dir)  # Check for specific attachment placeholders
        self.issue_tracker.print_summary()  # Print the issue summary

    # Fix image files without extensions
    def fix_image_extensions(self, resources_dir, input_dir):
        for file_name in os.listdir(resources_dir):
            file_path = os.path.join(resources_dir, file_name)
            if os.path.isfile(file_path) and not os.path.splitext(file_name)[1]:
                self.process_image_file(file_name, resources_dir, input_dir)

    # Process image files by detecting the image type and renaming accordingly
    def process_image_file(self, file_name, resources_dir, input_dir):
        file_path = os.path.join(resources_dir, file_name)
        try:
            with Image.open(file_path) as img:
                file_type = img.format.lower()  # Identify image type
                if file_type:
                    new_file_name = f"{file_name}.{file_type}"
                    new_file_path = os.path.join(resources_dir, new_file_name)
                    os.rename(file_path, new_file_path)  # Rename image with proper extension
                    logging.info(f"Renamed {file_name} to {new_file_name}")
                    self.update_markdown_references(file_name, new_file_name, input_dir)  # Update references in markdown
        except IOError:
            logging.warning(f"Could not identify {file_name}, skipping.")
            self.issue_tracker.add_issue("files_with_invalid_attachments", f"Invalid image file in _resources: {file_name}")

    # Update references in markdown files after renaming an image
    def update_markdown_references(self, old_name, new_name, input_dir):
        for root, _, files in os.walk(input_dir):
            for file in files:
                if file.endswith('.md'):
                    file_path = os.path.join(root, file)
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()

                    updated_content = content.replace(f'../_resources/{old_name}', f'../_resources/{new_name}')

                    if content != updated_content:
                        # Save the updated markdown file
                        with open(file_path, 'w', encoding='utf-8') as f:
                            f.write(updated_content)
                        logging.info(f"Updated references in {file_path}")

    # Download remote images linked in markdown files and save them locally
    def download_remote_images(self, input_dir, resources_dir):
        for root, _, files in os.walk(input_dir):
            for file in files:
                if file.endswith('.md'):
                    self.process_markdown_file_for_images(os.path.join(root, file), resources_dir)

    # Process markdown files to find and download remote images
    def process_markdown_file_for_images(self, file_path, resources_dir):
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        updated_content, success = self.process_image_urls(content, resources_dir)
        if success:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(updated_content)
            logging.info(f"Updated {file_path} with local image references.")

    # Download images found in URLs within markdown files
    def process_image_urls(self, content, resources_dir):
        pattern = r'!\[.*?\]\((https?://[^\s\)]+)(?:\s+"[^"]*")?\)'
        remote_images = re.findall(pattern, content)
        success = True

        for url in remote_images:
            try:
                image_name = self.download_and_save_image(url, resources_dir)  # Download and save image
                content = content.replace(url, f"../_resources/{image_name}")  # Update reference to local path
            except requests.exceptions.RequestException:
                self.issue_tracker.add_issue("files_with_download_issues", f"Failed to download {url}")
                success = False
        return content, success

    # Download an image from a given URL and save it locally
    def download_and_save_image(self, url, resources_dir):
        response = self.download_image_with_retries(url)  # Attempt to download image with retries
        content_length = int(response.headers.get('Content-Length', 0))
        if content_length > self.config.max_download_size:
            raise requests.exceptions.RequestException(f"Image at {url} exceeds max size limit.")
        ext = mimetypes.guess_extension(response.headers.get('Content-Type', ''))
        if not ext:
            ext = os.path.splitext(url)[1]  # Extract extension from URL if not found in headers
            if not ext:
                ext = '.jpg'  # Default to .jpg if no extension is available
        image_name = f"{hashlib.md5(url.encode('utf-8')).hexdigest()}{ext}"
        local_image_path = os.path.join(resources_dir, image_name)
        with open(local_image_path, 'wb') as f_img:
            f_img.write(response.content)  # Save downloaded image to disk
        logging.info(f"Downloaded {url} to {local_image_path}")
        return image_name

    # Download an image with retry attempts in case of failure
    def download_image_with_retries(self, url):
        for attempt in range(self.config.retry_attempts):
            try:
                response = self.session.get(url, stream=True, timeout=self.config.download_timeout)
                response.raise_for_status()  # Raise error if request failed
                return response
            except requests.exceptions.RequestException:
                if attempt + 1 < self.config.retry_attempts:
                    time.sleep(self.config.retry_delay)  # Wait before retrying
                else:
                    raise

    # Process each markdown and HTML file in the input directory recursively
    def process_folder_recursively(self, input_dir, output_dir, resources_dir):
        for root, dirs, files in os.walk(input_dir):
            for file in files:
                if file.endswith('.md') or file.endswith('.html'):
                    self.process_file(os.path.join(root, file), resources_dir, output_dir)

    # Check if the title extracted from a file is valid
    def is_valid_title(self, title):
        if not title or not title.strip():
            return False  # Empty or whitespace-only title

        stripped_title = title.strip()

        if stripped_title in ('-', '>', '>-'):
            return False

        if re.match(r'^<.*?>$', stripped_title) or re.search(r'<[^>]+>', stripped_title):
            return False

        if re.search(r'\.(jpg|jpeg|png|gif|pdf|html?)$', stripped_title, re.IGNORECASE):
            return False

        if re.match(r'https?://', stripped_title):
            return False

        if len(stripped_title) > self.config.max_filename_length:
            return False

        return True

    # Process each markdown or HTML file to extract metadata, convert content, and generate RTFD files
    def process_file(self, file_path, resources_dir, output_dir):
        try:
            front_matter, file_content = self.read_file_and_extract_content(file_path)  # Read and extract front matter
            title = self.determine_title(front_matter, file_path)  # Determine a title for the file
            file_content = self.insert_title_if_needed(file_content, title, file_path)  # Insert title if missing
            file_content, image_filenames, pdf_placeholders = self.process_attachments(file_content, resources_dir)  # Process attachments
            html_content = self.generate_html_content(file_content, file_path)  # Generate HTML content from markdown
            mutable_attributed_string = self.create_mutable_attributed_string(html_content, resources_dir, image_filenames, pdf_placeholders)  # Create an attributed string from HTML
            output_path = self.save_rtfd_file(mutable_attributed_string, output_dir, file_path)  # Save as RTFD file
            self.set_file_dates(output_path, front_matter, file_path)  # Set file creation and modification dates
        except Exception as e:
            logging.error(f"Error processing {file_path}: {e}")
            self.issue_tracker.add_issue("files_with_attachment_issues", f"Error processing {file_path}: {e}")

    # Read a file and extract its front matter
    def read_file_and_extract_content(self, file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            file_content = f.read()
        front_matter, file_content = self.extract_front_matter(file_content)  # Extract front matter from the content
        return front_matter, file_content

    # Determine the title of a file based on its front matter or default to filename
    def determine_title(self, front_matter, file_path):
        extracted_title = front_matter.get('title', '').strip()
        default_title = os.path.splitext(os.path.basename(file_path))[0]
        if self.is_valid_title(extracted_title):
            title = extracted_title
        else:
            title = default_title
        return title

    # Insert the title at the beginning of file content if it starts with an attachment
    def insert_title_if_needed(self, file_content, title, file_path):
        stripped_content = re.sub(r'^(\s|&nbsp;)+', '', file_content, flags=re.IGNORECASE)
        pattern = r'^(<img[^>]*?>|!\[.*?\]\(.*?\)|\[[^\]]*\]\(.*?\.pdf\)|\[\s*!\[.*?\]\(.*?\)\]\(.*?\))'
        if re.match(pattern, stripped_content, re.IGNORECASE):
            file_content = f"{title}\n\n{file_content}"
            logging.info(f"Inserted title '{title}' at the beginning of {file_path}")
        return file_content

    # Extract front matter from file content
    def extract_front_matter(self, file_content):
        front_matter = {}
        if file_content.startswith('---'):
            parts = file_content.split('---', 2)
            front_matter_block = parts[1].strip()
            file_content = parts[2] if len(parts) > 2 else ''
            for line in front_matter_block.splitlines():
                if ': ' in line:
                    key, value = line.split(': ', 1)
                    front_matter[key.strip()] = value.strip()
        return front_matter, file_content

    # Process attachments (e.g., images, PDFs) in file content
    def process_attachments(self, file_content, resources_dir):
        image_filenames = []
        pdf_placeholders = []
        attachment_pattern = re.compile(r'\[.*?\]\((.*?)\)')

        def replace_attachment(match):
            file_path = match.group(1)
            file_name = os.path.basename(file_path)
            absolute_path = os.path.join(resources_dir, file_name)
            if file_name.lower().endswith('.pdf'):
                return self.process_pdf_attachment(file_name, pdf_placeholders)
            elif file_name.lower().endswith(tuple(self.config.supported_formats)):
                return self.process_image_attachment(file_name, absolute_path, image_filenames)
            return match.group(0)

        processed_content = attachment_pattern.sub(replace_attachment, file_content)
        return processed_content, image_filenames, pdf_placeholders

    # Handle image attachments and add them to a list
    def process_image_attachment(self, file_name, absolute_path, image_filenames):
        image_filenames.append(file_name)
        return f'<img src="{absolute_path}" alt="{file_name}" title="{file_name}">'

    # Handle PDF attachments and add placeholders for them
    def process_pdf_attachment(self, file_name, pdf_placeholders):
        pdf_placeholders.append(file_name)
        return f'[[PDF_ATTACHMENT_{len(pdf_placeholders) - 1}]]'

    # Generate HTML content from markdown or HTML file content
    def generate_html_content(self, file_content, file_path):
        if file_path.endswith('.md'):
            html_body = markdown.markdown(file_content)  # Convert markdown to HTML
        else:
            html_body = file_content  # HTML content remains unchanged
        return f"<html><head>{self.config.custom_css}</head><body>{html_body}</body></html>"

    # Create a mutable attributed string from HTML content
    def create_mutable_attributed_string(self, html_content, resources_dir, image_filenames, pdf_placeholders):
        mutable_attributed_string = self.convert_html_to_attributed_string(html_content, resources_dir)  # Convert HTML
        self.set_attachment_filenames(mutable_attributed_string, image_filenames)  # Set filenames for image attachments
        self.embed_pdf_attachments(mutable_attributed_string, pdf_placeholders, resources_dir)  # Embed PDF attachments
        return mutable_attributed_string

    # Convert HTML content to a mutable attributed string (for RTFD conversion)
    def convert_html_to_attributed_string(self, html_content, resources_dir):
        html_data = html_content.encode('utf-8')
        ns_html_data = NSData.dataWithBytes_length_(html_data, len(html_data))
        options = {
            NSDocumentTypeDocumentOption: NSHTMLTextDocumentType,
            NSCharacterEncodingDocumentOption: NSUTF8StringEncoding,
            NSBaseURLDocumentOption: NSURL.fileURLWithPath_(resources_dir)
        }
        ns_attributed_string, _, error = NSAttributedString.alloc().initWithData_options_documentAttributes_error_(
            ns_html_data, options, None, None
        )
        if error:
            raise ValueError(f"Error creating attributed string: {error}")
        mutable_attributed_string = NSMutableAttributedString.alloc().initWithAttributedString_(ns_attributed_string)
        return mutable_attributed_string

    # Set filenames for image attachments in an attributed string
    def set_attachment_filenames(self, attributed_string, image_filenames):
        pos, length, image_index = 0, attributed_string.length(), 0
        while pos < length:
            attrs, effective_range = attributed_string.attributesAtIndex_longestEffectiveRange_inRange_(
                pos, None, (pos, length - pos)
            )
            attachment = attrs.get('NSAttachment') or attrs.get('NSAttachmentAttributeName')
            if attachment and image_index < len(image_filenames):
                attachment.fileWrapper().setPreferredFilename_(image_filenames[image_index])  # Set filename
                image_index += 1
            pos = effective_range[0] + effective_range[1]

    # Embed PDF attachments in an attributed string by replacing placeholders
    def embed_pdf_attachments(self, attributed_string, pdf_placeholders, resources_dir):
        for index, file_name in enumerate(pdf_placeholders):
            decoded_file_name = unquote(file_name)
            pdf_path = os.path.join(resources_dir, decoded_file_name)

            if not os.path.exists(pdf_path):
                logging.error(f"Invalid PDF attachment in {pdf_path}")
                self.issue_tracker.add_issue("files_with_invalid_attachments", f"Invalid PDF attachment in {pdf_path}")
                continue

            pdf_wrapper = NSFileWrapper.alloc().initWithPath_(pdf_path)
            if pdf_wrapper is None:
                logging.error(f"Could not create file wrapper for PDF {pdf_path}")
                self.issue_tracker.add_issue("files_with_invalid_attachments", f"Invalid PDF attachment in {pdf_path}")
                continue

            pdf_wrapper.setPreferredFilename_(decoded_file_name)
            attachment = NSTextAttachment.alloc().init()
            attachment.setFileWrapper_(pdf_wrapper)
            attachment_string = NSAttributedString.attributedStringWithAttachment_(attachment)

            placeholder = f'[[PDF_ATTACHMENT_{index}]]'
            placeholder_range = attributed_string.mutableString().rangeOfString_(placeholder)
            if placeholder_range.location != NSNotFound:
                attributed_string.replaceCharactersInRange_withAttributedString_(placeholder_range, attachment_string)
            else:
                logging.error(f"Placeholder {placeholder} not found in attributed string.")
                self.issue_tracker.add_issue("files_with_attachment_issues", f"Missing placeholder {placeholder} in attributed string.")

    # Save the converted content as an RTFD file
    def save_rtfd_file(self, mutable_attributed_string, output_dir, file_path):
        output_file_name = os.path.splitext(os.path.basename(file_path))[0] + '.rtfd'
        output_path = os.path.join(output_dir, output_file_name)

        # Ensure unique file name if file already exists
        output_path = self.get_unique_output_path(output_path)

        file_wrapper = mutable_attributed_string.RTFDFileWrapperFromRange_documentAttributes_(
            (0, mutable_attributed_string.length()), {}
        )

        success, error = file_wrapper.writeToURL_options_originalContentsURL_error_(
            NSURL.fileURLWithPath_(output_path), 0, None, None
        )
        if not success:
            logging.error(f"Failed to write RTFD file: {output_path}, Error: {error}")
            raise IOError(f"Failed to write RTFD file: {output_path}, Error: {error}")

        logging.info(f"RTFD file saved to {output_path}")
        return output_path

    # Get a unique output path to prevent overwriting existing files
    def get_unique_output_path(self, output_path):
        output_dir = os.path.dirname(output_path)
        base_name = os.path.splitext(os.path.basename(output_path))[0]
        unique_path = output_path
        suffix = 1
        while os.path.exists(unique_path):
            unique_path = os.path.join(output_dir, f"{base_name}_{suffix}.rtfd")
            suffix += 1
        return unique_path

    # Set file creation and modification dates based on front matter metadata
    def set_file_dates(self, output_path, front_matter, file_path):
        if 'created' in front_matter and 'updated' in front_matter:
            try:
                created_nsdate = NSDate.dateWithTimeIntervalSince1970_(
                    datetime.strptime(front_matter['created'], '%Y-%m-%d %H:%M:%SZ').timestamp())
                updated_nsdate = NSDate.dateWithTimeIntervalSince1970_(
                    datetime.strptime(front_matter['updated'], '%Y-%m-%d %H:%M:%SZ').timestamp())
                attributes = NSDictionary.dictionaryWithObjects_forKeys_(
                    [created_nsdate, updated_nsdate], [NSFileCreationDate, NSFileModificationDate]
                )
                file_manager = NSFileManager.defaultManager()
                success, error = file_manager.setAttributes_ofItemAtPath_error_(attributes, output_path, None)
                if not success:
                    self.issue_tracker.add_issue("files_with_issues", f"{file_path}: Failed to set file dates")
            except Exception as e:
                self.issue_tracker.add_issue("files_with_issues", f"{file_path}: Error setting file dates: {e}")
        else:
            self.issue_tracker.add_issue("files_with_invalid_front_matter", f"{file_path}: Missing date in front matter")

    # Check for large attachments in RTFD files
    def check_for_large_attachments(self, rtfd_output_dir):
        # Check each .rtfd package for attachments exceeding the large attachment threshold
        for root, dirs, files in os.walk(rtfd_output_dir):
            for dir_name in dirs:
                rtfd_package_path = os.path.join(root, dir_name)
                if rtfd_package_path.endswith('.rtfd'):
                    for file in os.listdir(rtfd_package_path):
                        attachment_path = os.path.join(rtfd_package_path, file)
                        if os.path.isfile(attachment_path) and os.path.getsize(attachment_path) > self.config.large_attachment_threshold:
                            self.issue_tracker.add_issue("large_attachment_files", f"{rtfd_package_path} contains a large attachment: {file}")

    # Check if RTFD files contain 'Attachment.png' placeholder
    def check_for_attachment_png(self, rtfd_output_dir):
        for root, dirs, _ in os.walk(rtfd_output_dir):
            for dir_name in dirs:
                rtfd_package_path = os.path.join(root, dir_name)
                if rtfd_package_path.endswith('.rtfd') and os.path.exists(
                        os.path.join(rtfd_package_path, 'Attachment.png')):
                    self.issue_tracker.add_issue("rtfd_files_with_attachment_png", f"{rtfd_package_path} contains Attachment.png")

# Entry point for the script
if __name__ == '__main__':
    converter = JoplinToRTFDConverter()
    input_directory = input("Enter the path of the folder where the markdown files are located: ").strip()
    converter.convert(input_directory)

