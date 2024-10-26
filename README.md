# Joplin-to-AppleNotes

Converts Joplin-exported Markdown files to RTFD format for importing into Apple Notes, preserving image and PDF attachments, formatting, and original creation/modification dates.

## Overview

This Python script is designed to convert Markdown (.md) files, exported by Joplin, into RTFD files that can be imported into Apple Notes on macOS. It processes a folder containing the .md files and outputs a folder with the converted RTFD files. The script handles images and PDFs within the Markdown files, downloading remote images and embedding them correctly into the RTFD format. It also preserves the original creation and modification dates of the notes.

There may be some errors during the conversion, especially with front matter or attachment processing. The script logs these issues, and at the end, it provides a list of problem files so you can manually review and edit those notes as needed.

**Disclaimer**: The script was generated with the help of ChatGPT and worked for the original author, but it might not work perfectly in every situation.

## Prerequisites

Make sure you have the following Python packages installed:
- `requests` (for HTTP requests)
- `Pillow` (PIL, for image processing)
- `markdown` (to convert Markdown to HTML)
- `pyobjc` (for Cocoa and other macOS libraries)

## Usage

1. **Export Notes from Joplin**: In Joplin, export your notes using `File > Export All > MD - Markdown + Front Matter` to an empty folder.
2. **Run the Script**: The script will prompt you for the folder containing the Markdown files. It will create an output directory called `rtfd_files` and start the conversion process.
3. **Import to Apple Notes**: After running the script, go to Apple Notes, choose `File > Import to Notes...` and select the `rtfd_files` folder.

## Features

- Converts Markdown files exported from Joplin to RTFD format.
- Preserves images and PDF attachments within the notes.
- Maintains original creation and modification dates.
- Downloads remote images linked in the Markdown files and embeds them in the RTFD output.

## Known Limitations

- This script only works on macOS.
- There may be issues with specific attachments, such as images or PDFs not being processed correctly.
- Some notes may contain images hosted online, which the script attempts to download. This may fail depending on the availability of the images.
- RTFD files sometimes end up with "Attachment.png" placeholder images that require further manual review.

## Logs and Error Handling

The script logs any issues encountered during the conversion process. At the end, it will provide a summary of the problem files so you can manually review and correct them if needed.

## License

This project is released under the **CC0 1.0 Universal (CC0 1.0)** license. This means you can use, modify, distribute, and build upon it freely, without any restrictions or need for attribution.
