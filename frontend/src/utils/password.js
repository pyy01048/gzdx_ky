export function passwordCategories(pwd) {
  let count = 0
  if (/[a-z]/.test(pwd)) count += 1
  if (/[A-Z]/.test(pwd)) count += 1
  if (/\d/.test(pwd)) count += 1
  if (/[^A-Za-z0-9]/.test(pwd)) count += 1
  return count
}
