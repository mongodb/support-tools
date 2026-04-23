"""
File decompression utilities for handling compressed log files.
Supports gzip (.gz), zip (.zip), bzip2 (.bz2), tar.gz (.tar.gz, .tgz), and tar.bz2 (.tar.bz2) formats.
"""
import gzip
import zipfile
import bz2
import tarfile
import io
import logging
from typing import BinaryIO, Iterator, Tuple, Optional

logger = logging.getLogger(__name__)


def decompress_gzip(file_obj: BinaryIO) -> Iterator[bytes]:
    """
    Decompress a gzip file and yield lines.
    
    Args:
        file_obj: File-like object containing gzip data
        
    Yields:
        Decompressed lines as bytes
    """
    file_obj.seek(0)
    with gzip.GzipFile(fileobj=file_obj, mode='rb') as gz:
        for line in gz:
            yield line


def decompress_bzip2(file_obj: BinaryIO) -> Iterator[bytes]:
    """
    Decompress a bzip2 file and yield lines.
    
    Args:
        file_obj: File-like object containing bzip2 data
        
    Yields:
        Decompressed lines as bytes
    """
    file_obj.seek(0)
    decompressor = bz2.BZ2Decompressor()
    buffer = b''
    
    while True:
        chunk = file_obj.read(8192)
        if not chunk:
            break
        try:
            decompressed = decompressor.decompress(chunk)
            buffer += decompressed
            while b'\n' in buffer:
                line, buffer = buffer.split(b'\n', 1)
                yield line + b'\n'
        except EOFError:
            break
    
    # Yield any remaining data
    if buffer:
        yield buffer


def decompress_zip(file_obj: BinaryIO) -> Iterator[bytes]:
    """
    Decompress a zip archive and yield lines from all contained files (concatenated).
    Handles nested compressed files (.gz, .bz2) inside the archive, which is common
    when mongosync log rotation produces compressed rotated log files.
    
    Args:
        file_obj: File-like object containing zip data
        
    Yields:
        Decompressed lines as bytes from all files in the archive
    """
    file_obj.seek(0)
    with zipfile.ZipFile(file_obj, 'r') as zf:
        file_list = zf.namelist()
        logger.info(f"ZIP archive contains {len(file_list)} file(s): {file_list}")
        
        for filename in file_list:
            # Skip directories
            if filename.endswith('/'):
                continue
            
            logger.info(f"Processing file from ZIP: {filename}")
            with zf.open(filename) as inner_file:
                if filename.lower().endswith('.gz'):
                    # Nested gzip file (e.g. mongosync.log.1.gz from log rotation)
                    logger.info(f"Decompressing nested gzip file: {filename}")
                    inner_bytes = io.BytesIO(inner_file.read())
                    with gzip.GzipFile(fileobj=inner_bytes, mode='rb') as gz:
                        for line in gz:
                            yield line
                elif filename.lower().endswith('.bz2'):
                    # Nested bzip2 file
                    logger.info(f"Decompressing nested bzip2 file: {filename}")
                    decompressed = bz2.decompress(inner_file.read())
                    for line in io.BytesIO(decompressed):
                        yield line
                else:
                    # Regular uncompressed file (e.g. mongosync.log)
                    for line in inner_file:
                        yield line


def decompress_tar(file_obj: BinaryIO, compression: str = 'gz') -> Iterator[bytes]:
    """
    Decompress a tar archive (tar.gz or tar.bz2) and yield lines from all contained files (concatenated).
    Handles nested compressed files (.gz, .bz2) inside the archive, which is common
    when mongosync log rotation produces compressed rotated log files.
    
    Args:
        file_obj: File-like object containing tar archive data
        compression: Compression type - 'gz' for gzip, 'bz2' for bzip2
        
    Yields:
        Decompressed lines as bytes from all files in the archive
    """
    file_obj.seek(0)
    mode = f'r:{compression}'
    
    with tarfile.open(fileobj=file_obj, mode=mode) as tf:
        members = tf.getmembers()
        file_names = [m.name for m in members if m.isfile()]
        logger.info(f"TAR archive contains {len(file_names)} file(s): {file_names}")
        
        for member in members:
            # Skip directories and non-regular files
            if not member.isfile():
                continue
            
            logger.info(f"Processing file from TAR: {member.name}")
            inner_file = tf.extractfile(member)
            if inner_file:
                if member.name.lower().endswith('.gz'):
                    # Nested gzip file (e.g. mongosync.log.1.gz from log rotation)
                    logger.info(f"Decompressing nested gzip file: {member.name}")
                    inner_bytes = io.BytesIO(inner_file.read())
                    with gzip.GzipFile(fileobj=inner_bytes, mode='rb') as gz:
                        for line in gz:
                            yield line
                elif member.name.lower().endswith('.bz2'):
                    # Nested bzip2 file
                    logger.info(f"Decompressing nested bzip2 file: {member.name}")
                    decompressed = bz2.decompress(inner_file.read())
                    for line in io.BytesIO(decompressed):
                        yield line
                else:
                    # Regular uncompressed file (e.g. mongosync.log)
                    for line in inner_file:
                        yield line


def get_file_extension(filename: str) -> str:
    """
    Get the file extension, handling compound extensions like .tar.gz.
    
    Args:
        filename: The filename to extract extension from
        
    Returns:
        The file extension (e.g., '.tar.gz', '.gz', '.zip')
    """
    import os
    filename_lower = filename.lower()
    
    # Check for compound extensions first
    compound_extensions = ['.tar.gz', '.tar.bz2']
    for ext in compound_extensions:
        if filename_lower.endswith(ext):
            return ext
    
    # Fall back to simple extension
    return os.path.splitext(filename)[1].lower()


def decompress_file(file_obj: BinaryIO, mime_type: str, filename: str = None) -> Iterator[bytes]:
    """
    Decompress a file based on its MIME type and return an iterator over lines.
    
    Args:
        file_obj: File-like object to decompress
        mime_type: Detected MIME type of the file
        filename: Original filename (used for extension-based detection when MIME is octet-stream or tar)
        
    Returns:
        Iterator yielding decompressed lines as bytes
        
    Raises:
        ValueError: If the MIME type is not a supported compressed format
    """
    from .app_config import EXTENSION_TO_COMPRESSION
    
    logger.info(f"Decompressing file with MIME type: {mime_type}, filename: {filename}")
    
    # Get file extension for tar archive detection
    ext = get_file_extension(filename) if filename else None
    compression_type = EXTENSION_TO_COMPRESSION.get(ext) if ext else None
    
    # Check for tar archives first (by extension, since MIME detection may vary)
    if compression_type == 'tar_gzip':
        logger.info(f"Using tar+gzip decompression based on file extension: {ext}")
        return decompress_tar(file_obj, compression='gz')
    elif compression_type == 'tar_bzip2':
        logger.info(f"Using tar+bzip2 decompression based on file extension: {ext}")
        return decompress_tar(file_obj, compression='bz2')
    
    # Handle by MIME type
    if mime_type in ('application/gzip', 'application/x-gzip'):
        return decompress_gzip(file_obj)
    elif mime_type in ('application/zip', 'application/x-zip-compressed'):
        return decompress_zip(file_obj)
    elif mime_type == 'application/x-bzip2':
        return decompress_bzip2(file_obj)
    elif mime_type == 'application/x-tar':
        # Plain tar with gzip compression (common for tar.gz detected as x-tar)
        logger.info("Using tar+gzip decompression for application/x-tar")
        return decompress_tar(file_obj, compression='gz')
    elif mime_type == 'application/octet-stream' and filename:
        # Fallback to extension-based detection for generic binary files
        if compression_type == 'gzip':
            logger.info(f"Using gzip decompression based on file extension: {ext}")
            return decompress_gzip(file_obj)
        elif compression_type == 'zip':
            logger.info(f"Using zip decompression based on file extension: {ext}")
            return decompress_zip(file_obj)
        elif compression_type == 'bzip2':
            logger.info(f"Using bzip2 decompression based on file extension: {ext}")
            return decompress_bzip2(file_obj)
        else:
            raise ValueError(f"Cannot determine compression type for octet-stream file with extension: {ext}")
    else:
        raise ValueError(f"Unsupported compressed MIME type: {mime_type}")


def is_compressed_mime_type(mime_type: str) -> bool:
    """
    Check if a MIME type represents a compressed file format.
    
    Args:
        mime_type: The MIME type to check
        
    Returns:
        True if the MIME type is a supported compressed format
    """
    from .app_config import COMPRESSED_MIME_TYPES
    return mime_type in COMPRESSED_MIME_TYPES


# =============================================================================
# Classified decompression functions - yield (line, file_type) tuples
# =============================================================================

def decompress_gzip_classified(file_obj: BinaryIO, filename: str) -> Iterator[Tuple[bytes, Optional[str]]]:
    """
    Decompress a gzip file and yield (line, file_type) tuples.
    
    Args:
        file_obj: File-like object containing gzip data
        filename: Original filename for classification
        
    Yields:
        Tuples of (decompressed line as bytes, file_type string or None)
    """
    from .app_config import classify_file_type
    
    file_type = classify_file_type(filename) if filename else None
    logger.info(f"Gzip file classified as: {file_type} (filename: {filename})")
    
    file_obj.seek(0)
    with gzip.GzipFile(fileobj=file_obj, mode='rb') as gz:
        for line in gz:
            yield (line, file_type)


def decompress_bzip2_classified(file_obj: BinaryIO, filename: str) -> Iterator[Tuple[bytes, Optional[str]]]:
    """
    Decompress a bzip2 file and yield (line, file_type) tuples.
    
    Args:
        file_obj: File-like object containing bzip2 data
        filename: Original filename for classification
        
    Yields:
        Tuples of (decompressed line as bytes, file_type string or None)
    """
    from .app_config import classify_file_type
    
    file_type = classify_file_type(filename) if filename else None
    logger.info(f"Bzip2 file classified as: {file_type} (filename: {filename})")
    
    file_obj.seek(0)
    decompressor = bz2.BZ2Decompressor()
    buffer = b''
    
    while True:
        chunk = file_obj.read(8192)
        if not chunk:
            break
        try:
            decompressed = decompressor.decompress(chunk)
            buffer += decompressed
            while b'\n' in buffer:
                line, buffer = buffer.split(b'\n', 1)
                yield (line + b'\n', file_type)
        except EOFError:
            break
    
    # Yield any remaining data
    if buffer:
        yield (buffer, file_type)


def decompress_zip_classified(file_obj: BinaryIO) -> Iterator[Tuple[bytes, Optional[str]]]:
    """
    Decompress a zip archive and yield (line, file_type) tuples from all contained files.
    Classifies each file based on its filename pattern.
    
    Args:
        file_obj: File-like object containing zip data
        
    Yields:
        Tuples of (decompressed line as bytes, file_type string or None)
    """
    from .app_config import classify_file_type
    
    file_obj.seek(0)
    with zipfile.ZipFile(file_obj, 'r') as zf:
        file_list = zf.namelist()
        logger.info(f"ZIP archive contains {len(file_list)} file(s): {file_list}")
        
        for filename in file_list:
            # Skip directories
            if filename.endswith('/'):
                continue
            
            file_type = classify_file_type(filename)
            logger.info(f"Processing file from ZIP: {filename} (classified as: {file_type})")
            
            # Skip files that don't match known patterns
            if file_type is None:
                logger.warning(f"Skipping unrecognized file: {filename}")
                continue
            
            with zf.open(filename) as inner_file:
                if filename.lower().endswith('.gz'):
                    # Nested gzip file
                    logger.info(f"Decompressing nested gzip file: {filename}")
                    inner_bytes = io.BytesIO(inner_file.read())
                    with gzip.GzipFile(fileobj=inner_bytes, mode='rb') as gz:
                        for line in gz:
                            yield (line, file_type)
                elif filename.lower().endswith('.bz2'):
                    # Nested bzip2 file
                    logger.info(f"Decompressing nested bzip2 file: {filename}")
                    decompressed = bz2.decompress(inner_file.read())
                    for line in io.BytesIO(decompressed):
                        yield (line, file_type)
                else:
                    # Regular uncompressed file
                    for line in inner_file:
                        yield (line, file_type)


def decompress_tar_classified(file_obj: BinaryIO, compression: str = 'gz') -> Iterator[Tuple[bytes, Optional[str]]]:
    """
    Decompress a tar archive and yield (line, file_type) tuples from all contained files.
    Classifies each file based on its filename pattern.
    
    Args:
        file_obj: File-like object containing tar archive data
        compression: Compression type - 'gz' for gzip, 'bz2' for bzip2
        
    Yields:
        Tuples of (decompressed line as bytes, file_type string or None)
    """
    from .app_config import classify_file_type
    
    file_obj.seek(0)
    mode = f'r:{compression}'
    
    with tarfile.open(fileobj=file_obj, mode=mode) as tf:
        members = tf.getmembers()
        file_names = [m.name for m in members if m.isfile()]
        logger.info(f"TAR archive contains {len(file_names)} file(s): {file_names}")
        
        for member in members:
            # Skip directories and non-regular files
            if not member.isfile():
                continue
            
            file_type = classify_file_type(member.name)
            logger.info(f"Processing file from TAR: {member.name} (classified as: {file_type})")
            
            # Skip files that don't match known patterns
            if file_type is None:
                logger.warning(f"Skipping unrecognized file: {member.name}")
                continue
            
            inner_file = tf.extractfile(member)
            if inner_file:
                if member.name.lower().endswith('.gz'):
                    # Nested gzip file
                    logger.info(f"Decompressing nested gzip file: {member.name}")
                    inner_bytes = io.BytesIO(inner_file.read())
                    with gzip.GzipFile(fileobj=inner_bytes, mode='rb') as gz:
                        for line in gz:
                            yield (line, file_type)
                elif member.name.lower().endswith('.bz2'):
                    # Nested bzip2 file
                    logger.info(f"Decompressing nested bzip2 file: {member.name}")
                    decompressed = bz2.decompress(inner_file.read())
                    for line in io.BytesIO(decompressed):
                        yield (line, file_type)
                else:
                    # Regular uncompressed file
                    for line in inner_file:
                        yield (line, file_type)


def decompress_file_classified(file_obj: BinaryIO, mime_type: str, filename: str = None) -> Iterator[Tuple[bytes, Optional[str]]]:
    """
    Decompress a file and return an iterator over (line, file_type) tuples.
    Each line is tagged with its file type based on the source filename pattern.
    
    Args:
        file_obj: File-like object to decompress
        mime_type: Detected MIME type of the file
        filename: Original filename (used for classification and extension-based detection)
        
    Returns:
        Iterator yielding tuples of (decompressed line as bytes, file_type string or None)
        
    Raises:
        ValueError: If the MIME type is not a supported compressed format
    """
    from .app_config import EXTENSION_TO_COMPRESSION
    
    logger.info(f"Decompressing file (classified) with MIME type: {mime_type}, filename: {filename}")
    
    # Get file extension for tar archive detection
    ext = get_file_extension(filename) if filename else None
    compression_type = EXTENSION_TO_COMPRESSION.get(ext) if ext else None
    
    # Check for tar archives first (by extension, since MIME detection may vary)
    if compression_type == 'tar_gzip':
        logger.info(f"Using tar+gzip decompression based on file extension: {ext}")
        return decompress_tar_classified(file_obj, compression='gz')
    elif compression_type == 'tar_bzip2':
        logger.info(f"Using tar+bzip2 decompression based on file extension: {ext}")
        return decompress_tar_classified(file_obj, compression='bz2')
    
    # Handle by MIME type
    if mime_type in ('application/gzip', 'application/x-gzip'):
        return decompress_gzip_classified(file_obj, filename)
    elif mime_type in ('application/zip', 'application/x-zip-compressed'):
        return decompress_zip_classified(file_obj)
    elif mime_type == 'application/x-bzip2':
        return decompress_bzip2_classified(file_obj, filename)
    elif mime_type == 'application/x-tar':
        # Plain tar with gzip compression (common for tar.gz detected as x-tar)
        logger.info("Using tar+gzip decompression for application/x-tar")
        return decompress_tar_classified(file_obj, compression='gz')
    elif mime_type == 'application/octet-stream' and filename:
        # Fallback to extension-based detection for generic binary files
        if compression_type == 'gzip':
            logger.info(f"Using gzip decompression based on file extension: {ext}")
            return decompress_gzip_classified(file_obj, filename)
        elif compression_type == 'zip':
            logger.info(f"Using zip decompression based on file extension: {ext}")
            return decompress_zip_classified(file_obj)
        elif compression_type == 'bzip2':
            logger.info(f"Using bzip2 decompression based on file extension: {ext}")
            return decompress_bzip2_classified(file_obj, filename)
        else:
            raise ValueError(f"Cannot determine compression type for octet-stream file with extension: {ext}")
    else:
        raise ValueError(f"Unsupported compressed MIME type: {mime_type}")

