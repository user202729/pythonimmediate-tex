return function(cmd)
	-- as mentioned in the .sty file this allows explicit flush after each write
	-- it's not easy to eliminate having to spawn 2 Python processes even with Lua https://stackoverflow.com/questions/8716527/interactive-popen-lua-call


	-- if this is a child process, should write to stderr, in which case cmd will be nil
	local send_content
	if cmd==nil then
		send_content=function(str)
			io.stderr:write(str.."\n")
			io.stderr:flush()
		end
	else
		process = io.popen(cmd, "w")
		send_content=function(str)
			process:write(str.."\n")
			process:flush()
		end
	end

	local function_table=lua.get_functions_table()

	-- https://tex.stackexchange.com/questions/632408/how-can-i-exclude-tex-macros-when-counting-a-strings-characters-in-lua/632464?noredirect=1#comment1623008_632464 this only work in Lua 5.3 or assume it's allocated sequentially
	local send_content_index=#function_table+1
	function_table[send_content_index]=function()
		send_content(token.scan_string())
	end

	local close_index=#function_table+1
	function_table[close_index]=function()
		process:close()
	end

	local bgroup=token.create(0x7b, 1)
	local egroup=token.create(0x7d, 2)

	token.put_next(
		bgroup,
		token.create("ifodd"),
		token.create(0x31, 12),
		token.create("fi"),
		egroup
	)
	local frozen_relax_tok=token.scan_toks(false, true)[1].tok
	local null_cs_tok=0x20000000  -- \csname\endcsname

	local cmdname_to_type={
		left_brace="1",
		right_brace="2",
		math_shift="3",
		tab_mark  ="4",
		mac_param ="6",
		sup_mark  ="7",
		sub_mark  ="8",
		spacer    ="A",
		letter    ="B",
		other_char="C",
	}
	local function serialize(tl)
		local result={}
		for _, v in ipairs(tl) do
			local s  -- serialized result of v
			local function handle_character(cat, index, char)
				if index<32 then
					s="^"..cat..utf8.char(index+64)
				else
					s=cat..char
				end
			end
			if v.csname~=nil then
				if v.active then
					handle_character("D", utf8.codepoint(v.csname), v.csname)
				elseif v.tok==frozen_relax_tok then
					s="R"
				elseif v.tok==null_cs_tok then
					s="\\ "
				else
					local c=v.csname
					s=""
					for i=1, #c do
						if c:byte(i)<33 then s=s.."*" end
					end
					s="\\"
					for i=1, #c do
						if c:byte(i)<33 then
							s=s.." "..string.char(c:byte(i)+64)
						else
							s=s..c:sub(i,i)
						end
					end
					s=s.." "
				end
			else
				assert(cmdname_to_type[v.cmdname]~=nil)
				handle_character(cmdname_to_type[v.cmdname], v.mode, utf8.char(v.mode))
			end
			result[#result+1]=s
		end
		return table.concat(result)
	end

	local serialize_index=#function_table+1
	function_table[serialize_index]=function()
		local result_token=token.get_next()
		assert(result_token.csname~=nil and not result_token.active)
		local tl=token.scan_toks()
		--token.set_macro(-2, result_token.csname, table.concat(result))
		tex.sprint{token.create "def", result_token, bgroup}
		tex.sprint(-2, serialize(tl))
		tex.sprint(egroup)
	end

	local send_balanced_index=#function_table+1
	function_table[send_balanced_index]=function()
		local tl=token.scan_toks()
		send_content(serialize(tl))
	end

	tex.print(
	[[\protected \luadef \_pythonimmediate_send_content:e ]] .. send_content_index ..
	[[\protected \luadef \_pythonimmediate_close_write: ]] .. close_index ..
	[[\protected \luadef \_pythonimmediate_tlserialize_nodot_unchecked:Nn ]] .. serialize_index ..
	[[\protected \luadef \_pythonimmediate_send_balanced_tl:n ]] .. send_balanced_index ..
	[[\relax]])
end
