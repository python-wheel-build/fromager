use pyo3::prelude::*;

#[pyfunction]
fn add(a: usize, b: usize) -> PyResult<usize> {
    Ok(a + b)
}

#[pymodule]
fn _lib(_py: Python<'_>, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(add, m)?)?;
    Ok(())
}
