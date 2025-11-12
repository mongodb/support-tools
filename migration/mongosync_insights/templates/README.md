# Template Structure

This directory contains the HTML templates for the Mongosync Insights application.

## Template Files

### `base.html`
The base template that all other templates extend. Contains:
- Common HTML structure (head, header, footer)
- Shared CSS styles
- Plotly.js script inclusion
- Template blocks for customization

### `home.html`
The main landing page template. Contains:
- File upload form for log analysis
- Live monitoring form with connection string input
- Version information display
- JavaScript for form validation

### `upload_results.html`
Template for displaying log analysis results. Contains:
- Plotly chart container
- JavaScript to render the uploaded log data visualization

### `metrics.html`
Template for live monitoring dashboard. Contains:
- Loading indicator
- Plotly chart container
- Auto-refresh JavaScript functionality
- Refresh interval display

### `error.html`
Generic error page template. Contains:
- Error message display
- Return to home link
- Consistent styling with other pages

## Template Variables

### `home.html`
- `connection_string_form`: HTML for the connection string input field

### `upload_results.html`
- `plot_json`: JSON data for the Plotly chart

### `metrics.html`
- `refresh_time`: Refresh interval in seconds (for display)
- `refresh_time_ms`: Refresh interval in milliseconds (for JavaScript)

### `error.html`
- `error_title`: Title of the error (optional)
- `error_message`: Description of the error (optional)

## Usage

Templates are used with Flask's `render_template()` function:

```python
return render_template('template_name.html', variable1=value1, variable2=value2)
```

## Benefits of Template Extraction

1. **Separation of Concerns**: HTML is separated from Python logic
2. **Maintainability**: Easier to modify UI without touching Python code
3. **Reusability**: Common elements are shared through base template
4. **Consistency**: Uniform styling and structure across all pages
5. **Developer Experience**: Better syntax highlighting and IDE support for HTML


### License

[Apache 2.0](http://www.apache.org/licenses/LICENSE-2.0)

DISCLAIMER
----------
Please note: all tools/ scripts in this repo are released for use "AS IS" **without any warranties of any kind**,
including, but not limited to their installation, use, or performance.  We disclaim any and all warranties, either 
express or implied, including but not limited to any warranty of noninfringement, merchantability, and/ or fitness 
for a particular purpose.  We do not warrant that the technology will meet your requirements, that the operation 
thereof will be uninterrupted or error-free, or that any errors will be corrected.

Any use of these scripts and tools is **at your own risk**.  There is no guarantee that they have been through 
thorough testing in a comparable environment and we are not responsible for any damage or data loss incurred with 
their use.

You are responsible for reviewing and testing any scripts you run *thoroughly* before use in any non-testing 
environment.

Thanks,  
The MongoDB Support Team