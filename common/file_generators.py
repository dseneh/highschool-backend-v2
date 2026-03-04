"""
Reusable file generation utilities for CSV and Excel exports

This module provides optimized, memory-efficient file generation utilities
that can be used across the application for data exports.

Excel files are generated using write-only mode for optimal performance and
consistency across all environments, regardless of dataset size. This approach
provides ~70% memory savings and ensures consistent output formatting.
"""

import csv
from datetime import datetime
from io import StringIO, BytesIO
from typing import List, Dict, Any, Optional, Tuple

from django.http import HttpResponse
from rest_framework.response import Response
from rest_framework import status


class FileGeneratorConfig:
    """Configuration for file generation"""
    
    def __init__(
        self,
        title: str,
        filename_prefix: str,
        headers: List[str],
        metadata: Optional[Dict[str, str]] = None,
    ):
        """
        Initialize file generator configuration
        
        Args:
            title: Title to display at the top of the file
            filename_prefix: Prefix for the generated filename
            headers: List of column headers
            metadata: Optional metadata to include (e.g., {"School": "ABC School", "Year": "2024"})
        """
        self.title = title
        self.filename_prefix = filename_prefix
        self.headers = headers
        self.metadata = metadata or {}


class CSVGenerator:
    """Generate CSV files with consistent formatting"""
    
    @staticmethod
    def generate(
        data: List[Dict[str, Any]],
        config: FileGeneratorConfig,
        include_totals: bool = False,
        totals_calculator: Optional[callable] = None,
    ) -> HttpResponse:
        """
        Generate a CSV file from data
        
        Args:
            data: List of dictionaries containing the row data
            config: FileGeneratorConfig instance
            include_totals: Whether to include a totals row
            totals_calculator: Optional function to calculate totals row
                              Should accept (data, headers) and return a list of values
        
        Returns:
            HttpResponse with CSV file
        """
        output = StringIO()
        writer = csv.writer(output)
        
        # Write title
        writer.writerow([config.title])
        
        # Write metadata
        for key, value in config.metadata.items():
            writer.writerow([f'{key}:', value])
        
        # Write timestamp
        writer.writerow(['Generated:', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
        writer.writerow([])  # Empty row
        
        # Write headers
        writer.writerow(config.headers)
        
        # Write data rows
        for row_data in data:
            row = [row_data.get(key, '') for key in CSVGenerator._get_data_keys(config.headers)]
            writer.writerow(CSVGenerator._format_row_values(row))
        
        # Write totals if requested
        if include_totals and totals_calculator:
            writer.writerow([])  # Empty row
            totals_row = totals_calculator(data, config.headers)
            writer.writerow(CSVGenerator._format_row_values(totals_row))
        
        # Create response
        output.seek(0)
        response = HttpResponse(output.getvalue(), content_type='text/csv')
        filename = f"{config.filename_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response
    
    @staticmethod
    def _get_data_keys(headers: List[str]) -> List[str]:
        """
        Convert headers to data keys (snake_case).
        Removes anything in parentheses to handle any currency/unit notation.
        
        Examples:
            "Tuition (L$)" -> "tuition"
            "Amount (US$)" -> "amount"
            "Price (€)" -> "price"
            "Weight (kg)" -> "weight"
            "Percent Paid (%)" -> "percent_paid"
        """
        import re
        keys = []
        for h in headers:
            # Remove anything in parentheses (currency symbols, units, etc.)
            # This handles any notation: ($), (L$), (US$), (€), (£), (%), (kg), etc.
            key = re.sub(r'\([^)]*\)', '', h)
            key = (
                key.lower()
                .replace(' ', '_')
                .replace('.', '')
                .strip('_')  # Remove leading/trailing underscores
            )
            keys.append(key)
        return keys
    
    @staticmethod
    def _format_row_values(row: List[Any]) -> List[str]:
        """Format row values for CSV output"""
        formatted = []
        for value in row:
            if isinstance(value, float):
                formatted.append(f"{value:.2f}")
            elif value is None:
                formatted.append('')
            else:
                formatted.append(str(value))
        return formatted


class ExcelGenerator:
    """Generate Excel files optimized for performance and consistency"""
    
    @staticmethod
    def generate(
        data: List[Dict[str, Any]],
        config: FileGeneratorConfig,
        include_totals: bool = False,
        totals_calculator: Optional[callable] = None,
    ) -> HttpResponse:
        """
        Generate an Excel file from data using write-only mode for optimal performance.
        
        Note: Styling has been removed for consistency across all environments and
        maximum performance. Write-only mode provides ~70% memory savings.
        
        Args:
            data: List of dictionaries containing the row data
            config: FileGeneratorConfig instance
            include_totals: Whether to include a totals row
            totals_calculator: Optional function to calculate totals row
        
        Returns:
            HttpResponse with Excel file or Response with error
        """
        try:
            import openpyxl
        except ImportError:
            return Response(
                {"detail": "Excel export requires openpyxl library to be installed"}, 
                status=status.HTTP_501_NOT_IMPLEMENTED
            )
        
        # Always use write-only mode for consistency and optimal performance
        wb = openpyxl.Workbook(write_only=True)
        ws = wb.create_sheet(config.title[:31])  # Excel sheet name limit
        
        # Write title and metadata
        ws.append([config.title])
        for key, value in config.metadata.items():
            ws.append([f'{key}:', value])
        ws.append(['Generated:', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
        ws.append([])  # Empty row
        ws.append(config.headers)
        
        # Write data rows
        data_keys = CSVGenerator._get_data_keys(config.headers)
        
        for row_data in data:
            row_values = [row_data.get(key, '') for key in data_keys]
            
            # Convert numeric strings to actual numbers for Excel, but preserve IDs
            converted_values = []
            for idx, value in enumerate(row_values):
                # Get the corresponding key to check if it's an ID field
                key = data_keys[idx] if idx < len(data_keys) else ''
                
                # Keep ID fields and text fields as strings to preserve leading zeros
                if isinstance(value, str) and value:
                    # Don't convert if it's an ID field (contains 'id') or starts with zero
                    if '_id' in key or key.endswith('_id') or key == 'id' or value.startswith('0'):
                        converted_values.append(value)  # Keep as string
                    else:
                        # Try to convert other numeric strings to numbers
                        try:
                            value = float(value)
                        except ValueError:
                            pass  # Keep as string if conversion fails
                        converted_values.append(value)
                else:
                    converted_values.append(value)
            
            ws.append(converted_values)
        
        # Write totals row if requested
        if include_totals and totals_calculator:
            totals_row = totals_calculator(data, config.headers)
            ws.append([])  # Empty row
            ws.append(totals_row)
        
        # Save to BytesIO
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        
        # Create response
        response = HttpResponse(
            output.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        filename = f"{config.filename_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response


class FileGenerator:
    """Main file generator facade for easy usage"""
    
    @staticmethod
    def generate_file(
        data: List[Dict[str, Any]],
        config: FileGeneratorConfig,
        file_format: str = 'excel',
        include_totals: bool = False,
        totals_calculator: Optional[callable] = None,
    ) -> HttpResponse:
        """
        Generate a file in the specified format
        
        Args:
            data: List of dictionaries containing the row data
            config: FileGeneratorConfig instance
            file_format: 'csv' or 'excel'
            include_totals: Whether to include a totals row
            totals_calculator: Optional function to calculate totals row
        
        Returns:
            HttpResponse with the generated file
        
        Example:
            ```python
            from common.file_generators import FileGenerator, FileGeneratorConfig
            
            config = FileGeneratorConfig(
                title="Student Billing Summary",
                filename_prefix="student_bills",
                headers=['Student ID', 'Name', 'Amount ($)'],
                metadata={'School': 'ABC School', 'Year': '2024'}
            )
            
            data = [
                {'student_id': '001', 'name': 'John Doe', 'amount': 1000.00},
                {'student_id': '002', 'name': 'Jane Smith', 'amount': 1500.00},
            ]
            
            def calculate_totals(data, headers):
                total_amount = sum(row['amount'] for row in data)
                return ['TOTALS', f'{len(data)} students', total_amount]
            
            response = FileGenerator.generate_file(
                data=data,
                config=config,
                file_format='excel',
                include_totals=True,
                totals_calculator=calculate_totals
            )
            ```
        """
        if file_format.lower() == 'csv':
            return CSVGenerator.generate(
                data=data,
                config=config,
                include_totals=include_totals,
                totals_calculator=totals_calculator,
            )
        elif file_format.lower() == 'excel':
            return ExcelGenerator.generate(
                data=data,
                config=config,
                include_totals=include_totals,
                totals_calculator=totals_calculator,
            )
        else:
            return Response(
                {"detail": f"Unsupported file format: {file_format}. Use 'csv' or 'excel'."}, 
                status=status.HTTP_400_BAD_REQUEST
            )


# Helper function for common totals calculations
def calculate_numeric_totals(
    data: List[Dict[str, Any]],
    headers: List[str],
    numeric_keys: List[str],
    prefix_columns: List[str] = None,
) -> List[Any]:
    """
    Calculate totals for numeric columns
    
    Args:
        data: List of row data
        headers: Column headers
        numeric_keys: Keys of numeric columns to sum
        prefix_columns: Values for non-numeric columns (e.g., ['TOTALS', 'X students'])
    
    Returns:
        List of values for the totals row
    """
    totals_row = prefix_columns or []
    data_keys = CSVGenerator._get_data_keys(headers)
    
    # Fill in empty strings for non-prefix, non-numeric columns
    prefix_count = len(prefix_columns) if prefix_columns else 0
    
    for idx, key in enumerate(data_keys):
        if idx < prefix_count:
            continue
        
        if key in numeric_keys:
            total = sum(row.get(key, 0) for row in data)
            totals_row.append(total)
        else:
            totals_row.append('')
    
    return totals_row
