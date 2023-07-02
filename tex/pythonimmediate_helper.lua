return function(cmd)
	-- as mentioned in the .sty file this allows explicit flush after each write
	-- it's not easy to eliminate having to spawn 2 Python processes even with Lua https://stackoverflow.com/questions/8716527/interactive-popen-lua-call
	local process = io.popen(cmd, "w")

	local function_table=lua.get_functions_table()

	-- https://tex.stackexchange.com/questions/632408/how-can-i-exclude-tex-macros-when-counting-a-strings-characters-in-lua/632464?noredirect=1#comment1623008_632464 this only work in Lua 5.3 or assume it's allocated sequentially
	local send_content_index=#function_table+1
	function_table[send_content_index]=function()
		 process:write(token.scan_string())
		 process:write("\n")
		 process:flush() 
	 end

	 local close_index=#function_table+1
	 function_table[close_index]=function()
		 process:close()
	 end

	 tex.print([[\protected \luadef \_pythonimmediate_send_content:e ]] .. send_content_index .. [[\protected \luadef \_pythonimmediate_close_write: ]] .. close_index .. [[\relax]])
 end
